"""add booking payment ledger and confirmation timestamp

Revision ID: c8d9e0f1a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-11-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reservation_fee_amount",
                sa.Float(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.alter_column("reservation_fee_amount", server_default=None)
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True)))

    op.create_table(
        "booking_payment_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=120), nullable=False),
        sa.Column("provider_reference", sa.String(length=120), nullable=True),
        sa.Column("amount_inr", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCEEDED",
                "FAILED",
                "REFUND_DUE",
                name="booking_payment_event_status_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("refund_due", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_event_id",
            name="uq_booking_payment_events_provider_event_id",
        ),
    )
    op.create_index(
        op.f("ix_booking_payment_events_booking_id"),
        "booking_payment_events",
        ["booking_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_booking_payment_events_booking_id"),
        table_name="booking_payment_events",
    )
    op.drop_table("booking_payment_events")

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("reservation_fee_amount")
