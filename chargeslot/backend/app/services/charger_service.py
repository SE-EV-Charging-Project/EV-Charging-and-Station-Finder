from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import enforce_operator_scope
from app.models.user import User, UserRole
from app.models.station import Station
from app.models.charger import Charger, Connector, ConnectorStatus
from app.schemas.charger import (
    ChargerCreateRequest,
    ChargerUpdateRequest,
    ConnectorCreateRequest,
    ConnectorUpdateRequest,
)
from app.services.audit_service import AuditService
from app.stations.validators import enforce_charger_values


class ChargerService:
    """
    Service handling Charger and Connector CRUD operations and Operator scoping
    (CS19-028 / REQ-F2-02 / Appendix B.4).
    """

    @staticmethod
    def add_charger_to_station(
        db: Session,
        user: User,
        station_id: int,
        data: ChargerCreateRequest,
        ip_address: str | None = None,
    ) -> Charger:
        """
        Adds a new charger with connectors to an operator's station (REQ-F2-02).
        Enforces station ownership and charger specifications validation.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        enforce_operator_scope(user, station.operator_id)

        # Enforce validation rules per REQ-F2-04
        charger_dict = data.model_dump()
        enforce_charger_values(charger_dict)

        charger = Charger(
            station_id=station.id,
            name=data.name,
            power_kw=data.power_kw,
            current_type=data.current_type,
            gateway_id=data.gateway_id,
            is_active=True,
            is_out_of_service=False,
        )
        db.add(charger)
        db.flush()  # Allocate charger ID for child connectors

        # Add initial connectors if specified
        for conn_req in data.connectors:
            connector = Connector(
                charger_id=charger.id,
                connector_type=conn_req.connector_type,
                status=ConnectorStatus.AVAILABLE,
            )
            db.add(connector)

        db.commit()
        db.refresh(charger)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CHARGER_CREATED",
            resource=f"Charger:{charger.id}",
            details=f"Charger '{charger.name or charger.id}' created under station {station_id}",
            ip_address=ip_address,
        )

        return charger

    @staticmethod
    def list_chargers(
        db: Session,
        user: User,
        station_id: int,
    ) -> tuple[list[Charger], int]:
        """
        Lists all chargers for a station (REQ-F1-12, REQ-F2-02).
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        enforce_operator_scope(user, station.operator_id)

        chargers = (
            db.query(Charger)
            .filter(Charger.station_id == station_id)
            .order_by(Charger.id.asc())
            .all()
        )
        return chargers, len(chargers)

    @staticmethod
    def get_charger(
        db: Session,
        user: User,
        charger_id: int,
    ) -> Charger:
        """
        Retrieves a single charger by ID with operator tenancy verification.
        """
        charger = db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charger with ID {charger_id} not found.",
            )

        enforce_operator_scope(user, charger.station.operator_id)
        return charger

    @staticmethod
    def update_charger(
        db: Session,
        user: User,
        charger_id: int,
        data: ChargerUpdateRequest,
        ip_address: str | None = None,
    ) -> Charger:
        """
        Edits charger power rating, current type, gateway ID, or status (REQ-F2-02).
        """
        charger = db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charger with ID {charger_id} not found.",
            )

        enforce_operator_scope(user, charger.station.operator_id)

        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            return charger

        # Enforce validation on updated fields
        enforce_charger_values(update_dict, partial=True)

        for field, value in update_dict.items():
            setattr(charger, field, value)

        db.commit()
        db.refresh(charger)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CHARGER_UPDATED",
            resource=f"Charger:{charger.id}",
            details=f"Charger {charger.id} updated by user {user.id}",
            ip_address=ip_address,
        )

        return charger

    @staticmethod
    def remove_charger(
        db: Session,
        user: User,
        charger_id: int,
        ip_address: str | None = None,
    ) -> int:
        """
        Removes a charger and all its connectors from a station (REQ-F2-02).
        """
        charger = db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charger with ID {charger_id} not found.",
            )

        enforce_operator_scope(user, charger.station.operator_id)

        cid = charger.id
        db.delete(charger)
        db.commit()

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CHARGER_DELETED",
            resource=f"Charger:{cid}",
            details=f"Charger {cid} removed from station {charger.station_id}",
            ip_address=ip_address,
        )

        return cid

    @staticmethod
    def add_connector(
        db: Session,
        user: User,
        charger_id: int,
        data: ConnectorCreateRequest,
        ip_address: str | None = None,
    ) -> Connector:
        """
        Adds a new connector to a charger (REQ-F2-02).
        """
        charger = db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charger with ID {charger_id} not found.",
            )

        enforce_operator_scope(user, charger.station.operator_id)

        connector = Connector(
            charger_id=charger.id,
            connector_type=data.connector_type,
            status=ConnectorStatus.AVAILABLE,
        )
        db.add(connector)
        db.commit()
        db.refresh(connector)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CONNECTOR_CREATED",
            resource=f"Connector:{connector.id}",
            details=f"Connector {connector.id} ({connector.connector_type.value}) added to charger {charger_id}",
            ip_address=ip_address,
        )

        return connector

    @staticmethod
    def update_connector(
        db: Session,
        user: User,
        connector_id: int,
        data: ConnectorUpdateRequest,
        ip_address: str | None = None,
    ) -> Connector:
        """
        Updates connector properties (connector type, status) (REQ-F2-02).
        """
        connector = db.query(Connector).filter(Connector.id == connector_id).first()
        if not connector:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector with ID {connector_id} not found.",
            )

        enforce_operator_scope(user, connector.charger.station.operator_id)

        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            return connector

        for field, value in update_dict.items():
            setattr(connector, field, value)

        db.commit()
        db.refresh(connector)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CONNECTOR_UPDATED",
            resource=f"Connector:{connector.id}",
            details=f"Connector {connector.id} updated by user {user.id}",
            ip_address=ip_address,
        )

        return connector

    @staticmethod
    def remove_connector(
        db: Session,
        user: User,
        connector_id: int,
        ip_address: str | None = None,
    ) -> int:
        """
        Removes an individual connector from a charger (REQ-F2-02).
        """
        connector = db.query(Connector).filter(Connector.id == connector_id).first()
        if not connector:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector with ID {connector_id} not found.",
            )

        enforce_operator_scope(user, connector.charger.station.operator_id)

        cid = connector.id
        db.delete(connector)
        db.commit()

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="CONNECTOR_DELETED",
            resource=f"Connector:{cid}",
            details=f"Connector {cid} deleted from charger {connector.charger_id}",
            ip_address=ip_address,
        )

        return cid
