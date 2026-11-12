import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, WebSocketException, status
from sqlalchemy.orm import Session

from app.api.deps import resolve_user_from_access_token
from app.dashboard.views import _load_authorized_station, get_live_connector_status_display
from app.discovery.views import _enum_to_str, compute_station_marker
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.station import Station
from app.models.user import User
from app.stations.moderation import StationModerationService


@dataclass
class _Subscription:
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop
    station_id: int
    user_id: int
    role: str
    include_inactive_chargers: bool


class StationStatusConnectionManager:
    """
    Thread-safe registry of open station dashboard WebSocket subscriptions
    for delivering connector status changes in real time (REQ-F2-19 / CS19-045).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: dict[int, list[_Subscription]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        *,
        station_id: int,
        user_id: int,
        role: str,
        include_inactive_chargers: bool,
    ) -> _Subscription:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        entry = _Subscription(
            websocket=websocket,
            loop=loop,
            station_id=station_id,
            user_id=user_id,
            role=role,
            include_inactive_chargers=include_inactive_chargers,
        )
        with self._lock:
            self._subscriptions.setdefault(station_id, []).append(entry)
        return entry

    def disconnect(self, station_id: int, websocket: WebSocket) -> None:
        with self._lock:
            entries = self._subscriptions.get(station_id)
            if not entries:
                return
            remaining = [e for e in entries if e.websocket is not websocket]
            if remaining:
                self._subscriptions[station_id] = remaining
            else:
                self._subscriptions.pop(station_id, None)

    def subscriber_count(self, station_id: int | None = None) -> int:
        with self._lock:
            if station_id is not None:
                return len(self._subscriptions.get(station_id, []))
            return sum(len(v) for v in self._subscriptions.values())

    def clear(self) -> None:
        with self._lock:
            self._subscriptions.clear()

    def _matching_subscriptions(
        self, station_id: int, *, charger_is_active: bool
    ) -> list[_Subscription]:
        with self._lock:
            entries = list(self._subscriptions.get(station_id, []))
        if charger_is_active:
            return entries
        return [e for e in entries if e.include_inactive_chargers]

    async def _send_safe(
        self, station_id: int, websocket: WebSocket, payload: dict[str, Any]
    ) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            self.disconnect(station_id, websocket)
            return False

    async def broadcast_event(
        self,
        station_id: int,
        payload: dict[str, Any],
        *,
        charger_is_active: bool = True,
    ) -> int:
        targets = self._matching_subscriptions(
            station_id, charger_is_active=charger_is_active
        )
        delivered = 0
        for sub in targets:
            if await self._send_safe(station_id, sub.websocket, payload):
                delivered += 1
        return delivered

    def publish_event_sync(
        self,
        station_id: int,
        payload: dict[str, Any],
        *,
        charger_is_active: bool = True,
    ) -> int:
        """
        Dispatch a status update payload from synchronous ingestion code to all
        open WebSocket dashboards subscribed to station_id.
        """
        targets = self._matching_subscriptions(
            station_id, charger_is_active=charger_is_active
        )
        if not targets:
            return 0

        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        delivered = 0
        for sub in targets:
            if sub.loop.is_closed():
                self.disconnect(station_id, sub.websocket)
                continue

            coro = self._send_safe(station_id, sub.websocket, payload)
            if running_loop is sub.loop:
                sub.loop.create_task(coro)
                delivered += 1
            elif sub.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, sub.loop)
                try:
                    if future.result(timeout=2.0):
                        delivered += 1
                except Exception:
                    self.disconnect(station_id, sub.websocket)
            else:
                coro.close()
                self.disconnect(station_id, sub.websocket)

        return delivered


status_connection_manager = StationStatusConnectionManager()


def extract_websocket_token(websocket: WebSocket, token: str | None = None) -> str:
    """Extract bearer JWT from ?token= query parameter or Authorization header."""
    if token and token.strip():
        return token.strip()

    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
        if candidate:
            return candidate

    raise WebSocketException(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Authentication token required via ?token= or Authorization Bearer header.",
    )


def authenticate_websocket_user(
    db: Session,
    websocket: WebSocket,
    token: str | None = None,
) -> User:
    """Authenticate WebSocket client using shared JWT access token validation."""
    raw_token = extract_websocket_token(websocket, token=token)
    try:
        return resolve_user_from_access_token(db=db, token=raw_token)
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc.detail),
        )


def authorize_station_subscription(
    db: Session,
    station_id: int | None,
    user: User,
) -> tuple[Station, bool]:
    """
    Validate station_id and enforce role/ownership visibility before accepting WS subscription.
    Returns (station, include_inactive_chargers).
    """
    if station_id is None or station_id <= 0:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="station_id must be a positive integer.",
        )

    try:
        return _load_authorized_station(db=db, user=user, station_id=station_id)
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc.detail),
        )


def build_snapshot_event(
    db: Session,
    station_id: int,
    user: User,
) -> dict[str, Any]:
    """Build initial live dashboard snapshot payload using REQ-F2-18 view serializer."""
    snapshot = get_live_connector_status_display(
        db=db,
        user=user,
        station_id=station_id,
    )
    return {
        "type": "snapshot",
        "station_id": station_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "data": snapshot.model_dump(mode="json"),
    }


def build_status_change_event(
    *,
    event_id: int,
    station: Station,
    charger: Charger,
    connector: Connector,
    previous_status: ConnectorStatus | None,
    new_status: ConnectorStatus,
    raw_status: str,
    observed_at: datetime,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Build real-time connector status change push payload (REQ-F2-19)."""
    obs_utc = (
        observed_at.replace(tzinfo=timezone.utc)
        if observed_at.tzinfo is None
        else observed_at.astimezone(timezone.utc)
    )
    is_oos = bool(charger.is_out_of_service)
    effective_status = ConnectorStatus.OFFLINE.value if is_oos else new_status.value
    marker = compute_station_marker(station)

    return {
        "type": "status_change",
        "event": "connector_status_changed",
        "event_id": event_id,
        "station_id": station.id,
        "charger_id": charger.id,
        "connector_id": connector.id,
        "connector_type": _enum_to_str(connector.connector_type),
        "gateway_id": charger.gateway_id,
        "previous_status": previous_status.value if previous_status else None,
        "status": effective_status,
        "raw_status": raw_status,
        "error_code": error_code,
        "is_active": bool(charger.is_active),
        "is_out_of_service": is_oos,
        "observed_at": obs_utc.isoformat(),
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "availability_summary": marker.model_dump(mode="json"),
    }


def publish_connector_status_change(
    *,
    event_id: int,
    station: Station,
    charger: Charger,
    connector: Connector,
    previous_status: ConnectorStatus | None,
    new_status: ConnectorStatus,
    raw_status: str,
    observed_at: datetime,
    error_code: str | None = None,
    manager: StationStatusConnectionManager | None = None,
) -> int:
    """
    Publish an ingested connector status update to all subscribed station dashboards.
    Inactive/unapproved stations are never broadcast to driver subscribers (BR-01).
    """
    target_manager = manager or status_connection_manager
    if target_manager.subscriber_count(station.id) == 0:
        return 0

    payload = build_status_change_event(
        event_id=event_id,
        station=station,
        charger=charger,
        connector=connector,
        previous_status=previous_status,
        new_status=new_status,
        raw_status=raw_status,
        observed_at=observed_at,
        error_code=error_code,
    )
    driver_visible_charger = bool(charger.is_active) and (
        StationModerationService.is_station_visible_to_drivers(station)
    )
    return target_manager.publish_event_sync(
        station.id,
        payload,
        charger_is_active=driver_visible_charger,
    )


async def station_status_websocket_handler(
    websocket: WebSocket,
    station_id: int | None,
    db: Session,
    token: str | None = None,
    manager: StationStatusConnectionManager | None = None,
) -> None:
    """
    Shared WebSocket handler for WS /ws/stations/status and /ws/stations/{station_id}/status.
    Authenticates caller, verifies station access, sends initial snapshot, and keeps
    subscription open for push status changes and client control actions.
    """
    active_manager = manager or status_connection_manager
    user = authenticate_websocket_user(db=db, websocket=websocket, token=token)
    station, include_inactive = authorize_station_subscription(
        db=db, station_id=station_id, user=user
    )

    role_str = _enum_to_str(user.role)
    await active_manager.connect(
        websocket,
        station_id=station.id,
        user_id=user.id,
        role=role_str,
        include_inactive_chargers=include_inactive,
    )

    try:
        snapshot_event = build_snapshot_event(db=db, station_id=station.id, user=user)
        await websocket.send_json(snapshot_event)

        while True:
            raw_text = await websocket.receive_text()
            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Invalid JSON message.",
                    }
                )
                continue

            if not isinstance(msg, dict):
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Expected JSON object payload.",
                    }
                )
                continue

            action = str(msg.get("action", "")).strip().lower()
            if action == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "station_id": station.id,
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
            elif action == "refresh":
                refreshed = build_snapshot_event(db=db, station_id=station.id, user=user)
                await websocket.send_json(refreshed)
            elif action == "unsubscribe":
                await websocket.send_json(
                    {
                        "type": "unsubscribed",
                        "station_id": station.id,
                    }
                )
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                break
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "UNSUPPORTED_ACTION",
                        "message": f"Unsupported action '{msg.get('action')}'.",
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        active_manager.disconnect(station.id, websocket)

