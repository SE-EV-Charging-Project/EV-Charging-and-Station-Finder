"""create station reviews table

Revision ID: d9e5f0a1b2c4
Revises: c8d4e9f1a2b3
Create Date: 2026-11-11 14:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9e5f0a1b2c4"
down_revision: Union[str, Sequence[str], None] = "c8d4e9f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "station_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_station_reviews_rating_range"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_station_reviews_booking_id"),
    )
    op.create_index(op.f("ix_station_reviews_booking_id"), "station_reviews", ["booking_id"], unique=False)
    op.create_index(op.f("ix_station_reviews_id"), "station_reviews", ["id"], unique=False)
    op.create_index(op.f("ix_station_reviews_station_id"), "station_reviews", ["station_id"], unique=False)
    op.create_index(op.f("ix_station_reviews_user_id"), "station_reviews", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_station_reviews_user_id"), table_name="station_reviews")
    op.drop_index(op.f("ix_station_reviews_station_id"), table_name="station_reviews")
    op.drop_index(op.f("ix_station_reviews_id"), table_name="station_reviews")
    op.drop_index(op.f("ix_station_reviews_booking_id"), table_name="station_reviews")
    op.drop_table("station_reviews")

