from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException

from app.discovery.reviews import (
    MAX_REVIEW_COMMENT_LENGTH,
    create_station_review,
    list_station_reviews,
    validate_review_input,
)
from app.models.audit import AuditLog
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.review import StationReview
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.utils.security import create_access_token, hash_password


def _make_user(
    db_session,
    *,
    name: str,
    email: str,
    phone: str,
    role: UserRole,
) -> User:
    user = User(
        name=name,
        email=email,
        phone=phone,
        hashed_password=hash_password("StrongPass!1"),
        role=role,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_station(
    db_session,
    operator: User,
    *,
    name: str = "Review Hub",
    status_val: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
) -> Station:
    station = Station(
        operator_id=operator.id,
        name=name,
        address="10 Indiranagar 100ft Rd, Bengaluru",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["WiFi", "Cafe"],
        operating_hours="24x7",
        contact_phone="+919800112244",
        contact_email="review@hub.example",
        price_per_kwh=15.0,
        status=status_val,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="Fast Unit A",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id=f"GW-REV-{station.id}",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector = Connector(
        charger_id=charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(station)
    return station


def _seed_booking(
    db_session,
    *,
    user: User,
    station: Station,
    status_val: BookingStatus = BookingStatus.COMPLETED,
) -> Booking:
    start = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    booking = Booking(
        user_id=user.id,
        station_id=station.id,
        start_soc=20,
        target_soc=80,
        est_duration_min=45,
        booking_type="manual",
        status=status_val,
        start_time=start,
        end_time=start + timedelta(minutes=45),
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    return booking


# ==============================================================================
# Unit Tests: TC-F2-15 (REQ-F2-15 / CS19-041)
# ==============================================================================


def test_validate_review_input_accepts_bounds_and_rejects_invalid():
    assert validate_review_input(1, 1, "  Great charger!  ") == "Great charger!"
    assert validate_review_input(1, 5, "   ") is None
    assert validate_review_input(1, 5, None) is None

    for bad_rating in (0, 6, -1, True):
        with pytest.raises(HTTPException) as exc_r:
            validate_review_input(1, bad_rating)
        assert exc_r.value.status_code == 422

    with pytest.raises(HTTPException) as exc_b:
        validate_review_input(0, 4)
    assert exc_b.value.status_code == 422

    with pytest.raises(HTTPException) as exc_s:
        validate_review_input(1, 4, station_id=0)
    assert exc_s.value.status_code == 422

    with pytest.raises(HTTPException) as exc_c:
        validate_review_input(1, 4, comment="x" * (MAX_REVIEW_COMMENT_LENGTH + 1))
    assert exc_c.value.status_code == 422


def test_create_review_once_per_completed_session_and_audit(db_session):
    driver = _make_user(
        db_session,
        name="Review Driver",
        email="rev.drv@example.com",
        phone="+919911000101",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Review Op",
        email="rev.op@example.com",
        phone="+919911000102",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)
    booking_1 = _seed_booking(db_session, user=driver, station=station, status_val=BookingStatus.COMPLETED)
    booking_2 = _seed_booking(db_session, user=driver, station=station, status_val=BookingStatus.COMPLETED)

    res_1 = create_station_review(
        db_session,
        user=driver,
        booking_id=booking_1.id,
        rating=5,
        comment="Super reliable CCS2!",
    )
    assert res_1.review.rating == 5
    assert res_1.review.comment == "Super reliable CCS2!"
    assert res_1.average_rating == 5.0
    assert res_1.total_reviews == 1

    # Duplicate review for the same completed session is blocked (409 Conflict)
    with pytest.raises(HTTPException) as exc_dup:
        create_station_review(
            db_session,
            user=driver,
            booking_id=booking_1.id,
            rating=4,
            comment="Trying again",
        )
    assert exc_dup.value.status_code == 409

    # A second completed session for the same driver/station can be reviewed
    res_2 = create_station_review(
        db_session,
        user=driver,
        booking_id=booking_2.id,
        rating=3,
        comment="Busy during evening",
    )
    assert res_2.average_rating == 4.0
    assert res_2.total_reviews == 2

    # Audit log recorded
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver.id,
            AuditLog.action == "STATION_REVIEW_CREATED",
        )
        .count()
        == 2
    )


def test_create_review_rejects_non_completed_foreign_hidden_and_operator(db_session):
    driver_a = _make_user(
        db_session,
        name="Driver A",
        email="rev.a@example.com",
        phone="+919911000201",
        role=UserRole.DRIVER,
    )
    driver_b = _make_user(
        db_session,
        name="Driver B",
        email="rev.b@example.com",
        phone="+919911000202",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op",
        email="rev.op2@example.com",
        phone="+919911000203",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)
    other_station = _seed_station(db_session, operator, name="Other Station")
    pending_station = _seed_station(
        db_session, operator, name="Pending Station", status_val=StationStatus.PENDING
    )

    confirmed_booking = _seed_booking(
        db_session, user=driver_a, station=station, status_val=BookingStatus.CONFIRMED
    )
    completed_a = _seed_booking(
        db_session, user=driver_a, station=station, status_val=BookingStatus.COMPLETED
    )
    pending_completed = _seed_booking(
        db_session, user=driver_a, station=pending_station, status_val=BookingStatus.COMPLETED
    )

    # Non-completed booking -> 400 Bad Request
    with pytest.raises(HTTPException) as exc_state:
        create_station_review(db_session, user=driver_a, booking_id=confirmed_booking.id, rating=5)
    assert exc_state.value.status_code == 400

    # Foreign driver -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_foreign:
        create_station_review(db_session, user=driver_b, booking_id=completed_a.id, rating=5)
    assert exc_foreign.value.status_code == 403

    # Operator role -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_op:
        create_station_review(db_session, user=operator, booking_id=completed_a.id, rating=5)
    assert exc_op.value.status_code == 403

    # Station mismatch -> 422
    with pytest.raises(HTTPException) as exc_mismatch:
        create_station_review(
            db_session,
            user=driver_a,
            booking_id=completed_a.id,
            rating=5,
            station_id=other_station.id,
        )
    assert exc_mismatch.value.status_code == 422

    # Unapproved station -> 404
    with pytest.raises(HTTPException) as exc_hidden:
        create_station_review(db_session, user=driver_a, booking_id=pending_completed.id, rating=5)
    assert exc_hidden.value.status_code == 404


# ==============================================================================
# Integration / API Tests: STC-F2-15
# ==============================================================================


def test_api_rate_a_station_and_station_detail_average_integration(client, db_session):
    driver_a = _make_user(
        db_session,
        name="Kavya Driver",
        email="kavya@example.com",
        phone="+919922000101",
        role=UserRole.DRIVER,
    )
    driver_b = _make_user(
        db_session,
        name="Rohan Driver",
        email="rohan@example.com",
        phone="+919922000102",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Grid Operator",
        email="grid.op@example.com",
        phone="+919922000103",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)
    booking_a = _seed_booking(db_session, user=driver_a, station=station, status_val=BookingStatus.COMPLETED)
    booking_b = _seed_booking(db_session, user=driver_b, station=station, status_val=BookingStatus.COMPLETED)

    # 1. Contract route: POST /api/v1/stations/rate-a-station
    res_1 = client.post(
        "/api/v1/stations/rate-a-station",
        json={
            "booking_id": booking_a.id,
            "rating": 5,
            "comment": "Fast charging and good cafe!",
        },
        headers=_auth_header(driver_a),
    )
    assert res_1.status_code == 201
    p1 = res_1.json()
    assert p1["average_rating"] == 5.0
    assert p1["total_reviews"] == 1
    assert p1["review"]["reviewer_name"] == "Kavya Driver"
    assert p1["review"]["station_id"] == station.id

    # 2. Path alias: POST /api/v1/stations/{station_id}/reviews (blank comment normalizes to None)
    res_2 = client.post(
        f"/api/v1/stations/{station.id}/reviews",
        json={
            "booking_id": booking_b.id,
            "rating": 4,
            "comment": "   ",
        },
        headers=_auth_header(driver_b),
    )
    assert res_2.status_code == 201
    p2 = res_2.json()
    assert p2["average_rating"] == 4.5
    assert p2["total_reviews"] == 2
    assert p2["review"]["comment"] is None

    # 3. List reviews via contract query & path alias routes
    res_list_q = client.get(
        f"/api/v1/stations/rate-a-station?station_id={station.id}",
        headers=_auth_header(driver_a),
    )
    assert res_list_q.status_code == 200
    assert res_list_q.json()["average_rating"] == 4.5
    assert res_list_q.json()["total_reviews"] == 2
    assert len(res_list_q.json()["reviews"]) == 2

    res_list_p = client.get(
        f"/api/v1/stations/{station.id}/reviews",
        headers=_auth_header(driver_b),
    )
    assert res_list_p.status_code == 200
    assert res_list_p.json()["total_reviews"] == 2

    # 4. Station detail screen (REQ-F2-13) surfaces computed average_rating & total_reviews
    res_detail = client.get(
        f"/api/v1/stations/station-detail?station_id={station.id}",
        headers=_auth_header(driver_a),
    )
    assert res_detail.status_code == 200
    assert res_detail.json()["average_rating"] == 4.5
    assert res_detail.json()["total_reviews"] == 2


def test_api_reviews_enforce_rbac_ownership_once_per_session_and_validation(client, db_session):
    driver_a = _make_user(
        db_session,
        name="Drv A",
        email="rbac.a@example.com",
        phone="+919922000201",
        role=UserRole.DRIVER,
    )
    driver_b = _make_user(
        db_session,
        name="Drv B",
        email="rbac.b@example.com",
        phone="+919922000202",
        role=UserRole.DRIVER,
    )
    owner_op = _make_user(
        db_session,
        name="Owner Op",
        email="rbac.op1@example.com",
        phone="+919922000203",
        role=UserRole.OPERATOR,
    )
    foreign_op = _make_user(
        db_session,
        name="Foreign Op",
        email="rbac.op2@example.com",
        phone="+919922000204",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, owner_op)
    completed = _seed_booking(db_session, user=driver_a, station=station, status_val=BookingStatus.COMPLETED)
    active = _seed_booking(db_session, user=driver_a, station=station, status_val=BookingStatus.ACTIVE)

    # Unauthenticated -> 401
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 5},
        ).status_code
        == 401
    )

    # Operator cannot submit a review -> 403
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 5},
            headers=_auth_header(owner_op),
        ).status_code
        == 403
    )

    # Owning operator can list station reviews -> 200; foreign operator -> 403
    assert (
        client.get(
            f"/api/v1/stations/{station.id}/reviews",
            headers=_auth_header(owner_op),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/stations/{station.id}/reviews",
            headers=_auth_header(foreign_op),
        ).status_code
        == 403
    )

    # Foreign driver cannot review Driver A's booking -> 403
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 5},
            headers=_auth_header(driver_b),
        ).status_code
        == 403
    )

    # Active (non-completed) booking rejected -> 400
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": active.id, "rating": 5},
            headers=_auth_header(driver_a),
        ).status_code
        == 400
    )

    # Out-of-range rating -> 422
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 6},
            headers=_auth_header(driver_a),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 0},
            headers=_auth_header(driver_a),
        ).status_code
        == 422
    )

    # Valid review succeeds (201), duplicate for same completed booking returns 409
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 5},
            headers=_auth_header(driver_a),
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/stations/rate-a-station",
            json={"booking_id": completed.id, "rating": 2},
            headers=_auth_header(driver_a),
        ).status_code
        == 409
    )
    assert db_session.query(StationReview).count() == 1

