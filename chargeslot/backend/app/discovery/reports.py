"""
Faulty Charger Reporting & Operator Forwarding Module
Requirement: REQ-F2-16 (Report faulty charger)
SRS Architecture Reference: HLD §Discovery, SDD §Discovery
Code File Reference: discovery/reports.py (SRS Page 35)
Story ID: CS19-042
Test Case ID: TC-F2-16, STC-F2-16
"""

from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.permissions import enforce_operator_scope
from app.models.charger import Charger
from app.models.fault_report import (
    FaultReportStatus,
    FaultSeverity,
    FaultType,
    FaultyChargerReport,
)
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.discovery import (
    FaultForwardingSummary,
    FaultyChargerReportCreateResponse,
    FaultyChargerReportItem,
    FaultyChargerReportListResponse,
)
from app.services.audit_service import AuditService
from app.stations.moderation import StationModerationService

MIN_FAULT_DESCRIPTION_LENGTH = 5
MAX_FAULT_DESCRIPTION_LENGTH = 1000
MAX_OPERATOR_NOTES_LENGTH = 500


def _validate_positive_id(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be a positive integer.",
        )


def validate_fault_report_input(
    charger_id: int,
    description: str,
    station_id: int | None = None,
    connector_id: int | None = None,
    fault_type: FaultType | str = FaultType.HARDWARE_FAULT,
    severity: FaultSeverity | str = FaultSeverity.MEDIUM,
) -> tuple[str, FaultType, FaultSeverity]:
    """
    Validate faulty charger report payload values (REQ-F2-16).
    Returns normalized (description, FaultType, FaultSeverity).
    """
    _validate_positive_id(charger_id, "charger_id")
    if station_id is not None:
        _validate_positive_id(station_id, "station_id")
    if connector_id is not None:
        _validate_positive_id(connector_id, "connector_id")

    if not isinstance(description, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Fault description must be a string.",
        )
    cleaned_desc = description.strip()
    if len(cleaned_desc) < MIN_FAULT_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fault description must be at least {MIN_FAULT_DESCRIPTION_LENGTH} characters.",
        )
    if len(cleaned_desc) > MAX_FAULT_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fault description cannot exceed {MAX_FAULT_DESCRIPTION_LENGTH} characters.",
        )

    try:
        parsed_type = fault_type if isinstance(fault_type, FaultType) else FaultType(str(fault_type).lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid fault_type '{fault_type}'.",
        ) from exc

    try:
        parsed_sev = severity if isinstance(severity, FaultSeverity) else FaultSeverity(str(severity).lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid severity '{severity}'.",
        ) from exc

    return cleaned_desc, parsed_type, parsed_sev


def resolve_operator_forwarding_channels(
    station: Station,
    operator: User | None,
) -> tuple[list[str], str | None, str | None]:
    """
    Determine delivery channels and operator contact targets when forwarding a fault report
    (REQ-F2-16). Always queues an in-app operator alert alongside enabled notification channels.
    """
    channels = ["in_app"]
    target_email = station.contact_email or (operator.email if operator else None)
    target_phone = station.contact_phone or (operator.phone if operator else None)

    if target_email and (operator is None or operator.notify_email):
        channels.append("email")
    if target_phone and (operator is None or operator.notify_sms):
        channels.append("sms")
    if operator and operator.notify_push:
        channels.append("push")

    return channels, target_email, target_phone


def build_fault_report_item(report: FaultyChargerReport) -> FaultyChargerReportItem:
    """Convert a FaultyChargerReport ORM record to FaultyChargerReportItem DTO."""
    reporter = getattr(report, "reporter", None)
    operator = getattr(report, "operator", None)
    station = getattr(report, "station", None)
    charger = getattr(report, "charger", None)
    channels = [c for c in (report.forwarded_channels or "in_app").split(",") if c]

    return FaultyChargerReportItem(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=reporter.name if reporter else f"Driver #{report.reporter_user_id}",
        operator_id=report.operator_id,
        station_id=report.station_id,
        station_name=station.name if station else f"Station #{report.station_id}",
        charger_id=report.charger_id,
        charger_name=charger.name if charger else f"Charger #{report.charger_id}",
        connector_id=report.connector_id,
        fault_type=report.fault_type.value if hasattr(report.fault_type, "value") else str(report.fault_type),
        severity=report.severity.value if hasattr(report.severity, "value") else str(report.severity),
        description=report.description,
        status=report.status.value if hasattr(report.status, "value") else str(report.status),
        forwarding=FaultForwardingSummary(
            operator_id=report.operator_id,
            operator_name=operator.name if operator else f"Operator #{report.operator_id}",
            organization=operator.operator_organization if operator else None,
            forwarded_to_email=report.forwarded_to_email,
            forwarded_to_phone=report.forwarded_to_phone,
            channels=channels,
            forwarded_at=report.forwarded_at,
        ),
        operator_notes=report.operator_notes,
        resolved_at=report.resolved_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _load_report_with_relations(db: Session, report_id: int) -> FaultyChargerReport | None:
    return (
        db.query(FaultyChargerReport)
        .options(
            joinedload(FaultyChargerReport.reporter),
            joinedload(FaultyChargerReport.operator),
            joinedload(FaultyChargerReport.station),
            joinedload(FaultyChargerReport.charger),
        )
        .filter(FaultyChargerReport.id == report_id)
        .first()
    )


def report_faulty_charger(
    db: Session,
    user: User,
    charger_id: int,
    description: str,
    station_id: int | None = None,
    connector_id: int | None = None,
    fault_type: FaultType | str = FaultType.HARDWARE_FAULT,
    severity: FaultSeverity | str = FaultSeverity.MEDIUM,
    ip_address: str | None = None,
) -> FaultyChargerReportCreateResponse:
    """
    Allow a driver to report a faulty charger and forward the report to the station's operator
    (REQ-F2-16 / CS19-042).
    """
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can submit faulty charger reports (REQ-F2-16).",
        )

    cleaned_desc, parsed_type, parsed_sev = validate_fault_report_input(
        charger_id=charger_id,
        description=description,
        station_id=station_id,
        connector_id=connector_id,
        fault_type=fault_type,
        severity=severity,
    )

    charger = (
        db.query(Charger)
        .options(
            joinedload(Charger.station).joinedload(Station.operator),
            joinedload(Charger.connectors),
        )
        .filter(Charger.id == charger_id)
        .first()
    )
    if not charger or not charger.station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charger with ID {charger_id} not found.",
        )

    station = charger.station
    if user.role == UserRole.DRIVER and (
        not StationModerationService.is_station_visible_to_drivers(station)
        or not charger.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charger with ID {charger_id} not found.",
        )

    if station_id is not None and charger.station_id != station_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="charger_id does not belong to the specified station_id.",
        )

    if connector_id is not None:
        charger_connector_ids = {c.id for c in (charger.connectors or [])}
        if connector_id not in charger_connector_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="connector_id does not belong to the specified charger.",
            )

    operator = station.operator
    channels, target_email, target_phone = resolve_operator_forwarding_channels(station, operator)
    now = datetime.now(timezone.utc)

    report = FaultyChargerReport(
        reporter_user_id=user.id,
        operator_id=station.operator_id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=connector_id,
        fault_type=parsed_type,
        severity=parsed_sev,
        description=cleaned_desc,
        status=FaultReportStatus.FORWARDED,
        forwarded_at=now,
        forwarded_channels=",".join(channels),
        forwarded_to_email=target_email,
        forwarded_to_phone=target_phone,
    )
    db.add(report)
    db.flush()

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="FAULTY_CHARGER_REPORTED",
        resource=f"charger:{charger.id}",
        details=(
            f"Driver reported fault ({parsed_type.value}/{parsed_sev.value}) on charger "
            f"{charger.name} (ID {charger.id}) at station {station.name} (ID {station.id})"
        ),
        ip_address=ip_address,
        commit=False,
    )
    AuditService.log_action(
        db=db,
        user_id=station.operator_id,
        action="FAULTY_CHARGER_REPORT_FORWARDED",
        resource=f"fault_report:{report.id}",
        details=(
            f"Fault report #{report.id} for charger {charger.name} (station ID {station.id}) "
            f"forwarded to operator ID {station.operator_id} via {','.join(channels)}"
        ),
        ip_address=ip_address,
        commit=False,
    )
    db.commit()

    loaded = _load_report_with_relations(db, report.id)
    return FaultyChargerReportCreateResponse(
        message="Faulty charger report submitted and forwarded to the station operator.",
        report=build_fault_report_item(loaded),
    )


def list_fault_reports(
    db: Session,
    user: User,
    station_id: int | None = None,
) -> FaultyChargerReportListResponse:
    """
    List faulty charger reports scoped to the caller's role (REQ-F2-16):
    - Drivers see only reports they submitted.
    - Operators see forwarded reports for their own stations (403 on foreign station_id, REQ-F1-12).
    - Admins have global scope.
    """
    if station_id is not None:
        _validate_positive_id(station_id, "station_id")

    query = db.query(FaultyChargerReport).options(
        joinedload(FaultyChargerReport.reporter),
        joinedload(FaultyChargerReport.operator),
        joinedload(FaultyChargerReport.station),
        joinedload(FaultyChargerReport.charger),
    )

    if user.role == UserRole.DRIVER:
        query = query.filter(FaultyChargerReport.reporter_user_id == user.id)
        if station_id is not None:
            query = query.filter(FaultyChargerReport.station_id == station_id)
    else:
        if station_id is not None:
            station = db.query(Station).filter(Station.id == station_id).first()
            if not station:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Station with ID {station_id} not found.",
                )
            enforce_operator_scope(user, station.operator_id)
            query = query.filter(FaultyChargerReport.station_id == station_id)
        elif user.role == UserRole.OPERATOR:
            query = query.filter(FaultyChargerReport.operator_id == user.id)

    reports = query.order_by(
        FaultyChargerReport.created_at.desc(),
        FaultyChargerReport.id.desc(),
    ).all()

    return FaultyChargerReportListResponse(
        total=len(reports),
        reports=[build_fault_report_item(r) for r in reports],
    )


def update_fault_report_status(
    db: Session,
    user: User,
    report_id: int,
    new_status: FaultReportStatus,
    operator_notes: str | None = None,
    ip_address: str | None = None,
) -> FaultyChargerReportItem:
    """
    Allow owning operator (or Admin) to acknowledge or resolve a forwarded fault report
    (REQ-F2-16 / REQ-F1-12).
    """
    _validate_positive_id(report_id, "report_id")

    report = _load_report_with_relations(db, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fault report with ID {report_id} not found.",
        )

    enforce_operator_scope(user, report.operator_id)

    if new_status == FaultReportStatus.FORWARDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot transition fault report back to forwarded.",
        )

    cleaned_notes = operator_notes.strip() if isinstance(operator_notes, str) else None
    if cleaned_notes and len(cleaned_notes) > MAX_OPERATOR_NOTES_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"operator_notes cannot exceed {MAX_OPERATOR_NOTES_LENGTH} characters.",
        )

    report.status = new_status
    if cleaned_notes is not None:
        report.operator_notes = cleaned_notes or None
    if new_status == FaultReportStatus.RESOLVED and report.resolved_at is None:
        report.resolved_at = datetime.now(timezone.utc)

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="FAULTY_CHARGER_REPORT_STATUS_UPDATED",
        resource=f"fault_report:{report.id}",
        details=f"Fault report #{report.id} updated to status '{new_status.value}'",
        ip_address=ip_address,
        commit=False,
    )
    db.commit()
    db.refresh(report)
    return build_fault_report_item(report)

