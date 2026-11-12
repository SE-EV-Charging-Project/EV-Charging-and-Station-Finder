"""
Station Rating & Review Module
Requirement: REQ-F2-15 (Rate a station)
SRS Architecture Reference: HLD §Discovery, SDD §Discovery
Code File Reference: discovery/reviews.py (SRS Page 35)
Story ID: CS19-041
Test Case ID: TC-F2-15, STC-F2-15
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.permissions import enforce_operator_scope
from app.discovery.views import compute_station_rating_summary
from app.models.booking import Booking, BookingStatus
from app.models.review import StationReview
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.discovery import (
    StationReviewCreateResponse,
    StationReviewItem,
    StationReviewListResponse,
)
from app.services.audit_service import AuditService
from app.stations.moderation import StationModerationService

MAX_REVIEW_COMMENT_LENGTH = 1000


def validate_review_input(
    booking_id: int,
    rating: int,
    comment: str | None = None,
    station_id: int | None = None,
) -> str | None:
    """
    Validate station rating (1-5) and optional review text (REQ-F2-15).
    Returns normalized comment text (or None if blank/absent).
    """
    if isinstance(booking_id, bool) or not isinstance(booking_id, int) or booking_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="booking_id must be a positive integer.",
        )

    if station_id is not None and (
        isinstance(station_id, bool) or not isinstance(station_id, int) or station_id <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id must be a positive integer.",
        )

    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rating must be an integer between 1 and 5 (REQ-F2-15).",
        )

    if comment is None:
        return None

    cleaned = comment.strip()
    if len(cleaned) > MAX_REVIEW_COMMENT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Review comment cannot exceed {MAX_REVIEW_COMMENT_LENGTH} characters.",
        )
    return cleaned or None


def build_review_item(review: StationReview) -> StationReviewItem:
    """Convert a StationReview ORM object into a StationReviewItem DTO."""
    reviewer = getattr(review, "user", None)
    return StationReviewItem(
        id=review.id,
        user_id=review.user_id,
        reviewer_name=reviewer.name if reviewer else f"Driver #{review.user_id}",
        station_id=review.station_id,
        booking_id=review.booking_id,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def create_station_review(
    db: Session,
    user: User,
    booking_id: int,
    rating: int,
    comment: str | None = None,
    station_id: int | None = None,
    ip_address: str | None = None,
) -> StationReviewCreateResponse:
    """
    Submit a rating (1-5) and optional review for a station once per completed session
    (REQ-F2-15 / CS19-041).
    """
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can rate and review charging stations (REQ-F2-15).",
        )

    cleaned_comment = validate_review_input(
        booking_id=booking_id,
        rating=rating,
        comment=comment,
        station_id=station_id,
    )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charging session/booking with ID {booking_id} not found.",
        )

    if booking.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You can only review stations for your own completed sessions.",
        )

    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed charging sessions can be rated and reviewed (REQ-F2-15).",
        )

    resolved_station_id = booking.station_id
    if resolved_station_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Completed booking is missing an associated station_id.",
        )

    if station_id is not None and station_id != resolved_station_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id does not match the station of the completed session.",
        )

    station = (
        db.query(Station)
        .options(joinedload(Station.reviews))
        .filter(Station.id == resolved_station_id)
        .first()
    )
    if not station or (
        user.role == UserRole.DRIVER
        and not StationModerationService.is_station_visible_to_drivers(station)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {resolved_station_id} not found.",
        )

    existing_review = (
        db.query(StationReview)
        .filter(StationReview.booking_id == booking_id)
        .first()
    )
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted a review for this completed session (REQ-F2-15).",
        )

    review = StationReview(
        user_id=user.id,
        station_id=resolved_station_id,
        booking_id=booking_id,
        rating=rating,
        comment=cleaned_comment,
    )
    db.add(review)
    db.flush()

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="STATION_REVIEW_CREATED",
        resource=f"station:{resolved_station_id}",
        details=(
            f"Driver rated station {station.name} (ID {resolved_station_id}) "
            f"{rating}/5 for completed booking ID {booking_id}"
        ),
        ip_address=ip_address,
        commit=False,
    )
    db.commit()
    db.refresh(review)
    review.user = user
    db.refresh(station)

    avg_rating, total_reviews = compute_station_rating_summary(station)

    return StationReviewCreateResponse(
        message="Station review submitted successfully.",
        review=build_review_item(review),
        average_rating=avg_rating,
        total_reviews=total_reviews,
    )


def list_station_reviews(
    db: Session,
    user: User,
    station_id: int,
) -> StationReviewListResponse:
    """
    Retrieve reviews and aggregated rating summary for a station (REQ-F2-15).
    - Drivers only see reviews of approved, active stations (BR-01).
    - Operators are scoped to their own stations (REQ-F1-12).
    """
    if isinstance(station_id, bool) or not isinstance(station_id, int) or station_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id must be a positive integer.",
        )

    station = (
        db.query(Station)
        .options(joinedload(Station.reviews).joinedload(StationReview.user))
        .filter(Station.id == station_id)
        .first()
    )
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found.",
        )

    if user.role == UserRole.DRIVER:
        if not StationModerationService.is_station_visible_to_drivers(station):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )
    else:
        enforce_operator_scope(user, station.operator_id)

    avg_rating, total_reviews = compute_station_rating_summary(station)
    sorted_reviews = sorted(
        station.reviews or [],
        key=lambda r: (r.created_at, r.id),
        reverse=True,
    )

    return StationReviewListResponse(
        station_id=station.id,
        average_rating=avg_rating,
        total_reviews=total_reviews,
        reviews=[build_review_item(r) for r in sorted_reviews],
    )

