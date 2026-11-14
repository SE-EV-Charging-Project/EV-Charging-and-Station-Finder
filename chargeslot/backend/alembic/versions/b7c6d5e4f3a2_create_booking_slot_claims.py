"""create atomic booking slot claims

Revision ID: b7c6d5e4f3a2
Revises: a9b8c7d6e5f4
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c6d5e4f3a2"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "booking_slot_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("slot_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "charger_id",
            "slot_start_time",
            name="uq_booking_slot_claim_charger_start",
        ),
    )
    op.create_index(
        op.f("ix_booking_slot_claims_booking_id"),
        "booking_slot_claims",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_slot_claims_charger_id"),
        "booking_slot_claims",
        ["charger_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_slot_claims_charger_id"), table_name="booking_slot_claims")
    op.drop_index(op.f("ix_booking_slot_claims_booking_id"), table_name="booking_slot_claims")
    op.drop_table("booking_slot_claims")
