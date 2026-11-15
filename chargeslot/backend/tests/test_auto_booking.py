from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from app.booking.slots import _score_candidate_slots, auto_book_slot
from app.models.booking import BookingStatus
from app.models.user import User, UserRole
from app.schemas.booking import RecommendedSlotItem


def _candidate(
    *,
    start_time: datetime,
    estimated_cost: float | None = 10.0,
    charging_time: float = 30.0,
) -> RecommendedSlotItem:
    return RecommendedSlotItem(
        rank=0,
        station_id=1,
        station_name="Reachable station",
        charger_id=2,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        energy_required_kwh=10.0,
        estimated_charging_time_minutes=charging_time,
        slot_length_minutes=45,
        price_per_kwh=5.0 if estimated_cost is not None else None,
        estimated_cost=estimated_cost,
    )


def test_candidate_scoring_uses_equal_normalized_factors_and_flags_missing_data():
    now = datetime.now(timezone.utc)
    earlier = _candidate(
        start_time=now + timedelta(days=1),
        estimated_cost=20.0,
        charging_time=45.0,
    )
    later = _candidate(
        start_time=now + timedelta(days=4),
        estimated_cost=10.0,
        charging_time=45.0,
    )
    middle_earlier = _candidate(
        start_time=now + timedelta(days=2),
        estimated_cost=15.0,
        charging_time=30.0,
    )
    middle_later = _candidate(
        start_time=now + timedelta(days=3),
        estimated_cost=15.0,
        charging_time=60.0,
    )

    scored = _score_candidate_slots([later, middle_later, earlier, middle_earlier])
    scores_by_start = {item.start_time: item.score for item in scored}

    assert scores_by_start[earlier.start_time] == scores_by_start[later.start_time]
    assert scored[0].rank == 1
    assert scored[0].available_factors == [
        "arrival_time",
        "price",
        "charging_time",
    ]
    assert "detour" in scored[0].unavailable_factors
    assert "reliability" in scored[0].unavailable_factors


def test_candidate_without_price_is_not_given_a_fabricated_price_score():
    item = _candidate(
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        estimated_cost=None,
    )

    scored = _score_candidate_slots([item])[0]

    assert "price" not in scored.available_factors
    assert "price" in scored.unavailable_factors
    assert "detour" in scored.unavailable_factors
    assert "reliability" in scored.unavailable_factors


def test_auto_book_confirm_first_suggests_without_creating_a_hold(
    db_session,
    monkeypatch,
):
    user = User(id=3, role=UserRole.DRIVER)
    candidate = _candidate(
        start_time=datetime.now(timezone.utc) + timedelta(days=1, hours=2)
    )
    monkeypatch.setattr(
        "app.booking.slots.find_reachable_stations",
        lambda **_: SimpleNamespace(stations=[SimpleNamespace(id=1)]),
    )
    monkeypatch.setattr(
        "app.booking.slots._candidate_slots",
        lambda **_: [candidate],
    )
    hold_calls = []
    monkeypatch.setattr(
        "app.booking.slots._create_slot_booking",
        lambda **kwargs: hold_calls.append(kwargs),
    )

    result = auto_book_slot(
        db=db_session,
        user=user,
        vehicle_id=5,
        latitude=12.9,
        longitude=77.6,
        slot_date=datetime.now(timezone.utc).date() + timedelta(days=1),
    )

    assert result.status == "suggested"
    assert result.selected_slot is not None
    assert "detour" in result.unavailable_factors
    assert hold_calls == []


def test_auto_book_immediately_creates_a_payment_hold(db_session, monkeypatch):
    user = User(id=3, role=UserRole.DRIVER)
    candidate = _candidate(
        start_time=datetime.now(timezone.utc) + timedelta(days=1, hours=2)
    )
    booking = SimpleNamespace(
        id=42,
        status=BookingStatus.HELD,
        reservation_fee_amount=5.0,
        hold_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "app.booking.slots.find_reachable_stations",
        lambda **_: SimpleNamespace(stations=[SimpleNamespace(id=1)]),
    )
    monkeypatch.setattr(
        "app.booking.slots._candidate_slots",
        lambda **_: [candidate],
    )
    calls = []

    def create_hold(**kwargs):
        calls.append(kwargs)
        return booking, 10.0, 45, 30.0

    monkeypatch.setattr("app.booking.slots._create_slot_booking", create_hold)

    result = auto_book_slot(
        db=db_session,
        user=user,
        vehicle_id=5,
        latitude=12.9,
        longitude=77.6,
        slot_date=datetime.now(timezone.utc).date() + timedelta(days=1),
        confirmation_mode="book_immediately",
    )

    assert result.status == "held"
    assert result.booking_id == 42
    assert result.booking_status == BookingStatus.HELD.value
    assert result.reservation_fee_amount == 5.0
    assert len(calls) == 1
    assert calls[0]["booking_status"] == BookingStatus.HELD


def test_auto_book_returns_future_reachable_alternatives_when_date_is_full(
    db_session,
    monkeypatch,
):
    user = User(id=3, role=UserRole.DRIVER)
    requested_date = date.today() + timedelta(days=1)
    later_candidate = _candidate(
        start_time=datetime.combine(
            requested_date + timedelta(days=1),
            time(10, 0),
            tzinfo=timezone.utc,
        )
    )
    monkeypatch.setattr(
        "app.booking.slots.find_reachable_stations",
        lambda **_: SimpleNamespace(stations=[SimpleNamespace(id=1)]),
    )
    monkeypatch.setattr(
        "app.booking.slots._candidate_slots",
        lambda **kwargs: (
            [later_candidate]
            if kwargs["slot_date"] == requested_date + timedelta(days=1)
            else []
        ),
    )

    result = auto_book_slot(
        db=db_session,
        user=user,
        vehicle_id=5,
        latitude=12.9,
        longitude=77.6,
        slot_date=requested_date,
    )

    assert result.status == "no_slot"
    assert result.selected_slot is None
    assert len(result.alternatives) == 1
    assert result.alternatives[0].start_time.date() == requested_date + timedelta(days=1)
