"""create charging session meter readings

Revision ID: f4a6b8c0d2e4
Revises: e3f4a5b6c7d8
Create Date: 2026-11-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a6b8c0d2e4"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "charging_session_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("power_kw", sa.Float(), nullable=False),
        sa.Column("energy_meter_kwh", sa.Float(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_charging_session_readings_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_charging_session_readings_booking_id"),
        "charging_session_readings",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_readings_charger_id"),
        "charging_session_readings",
        ["charger_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_readings_connector_id"),
        "charging_session_readings",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_readings_transaction_id"),
        "charging_session_readings",
        ["transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_readings_observed_at"),
        "charging_session_readings",
        ["observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_charging_session_readings_observed_at"),
        table_name="charging_session_readings",
    )
    op.drop_index(
        op.f("ix_charging_session_readings_transaction_id"),
        table_name="charging_session_readings",
    )
    op.drop_index(
        op.f("ix_charging_session_readings_connector_id"),
        table_name="charging_session_readings",
    )
    op.drop_index(
        op.f("ix_charging_session_readings_charger_id"),
        table_name="charging_session_readings",
    )
    op.drop_index(
        op.f("ix_charging_session_readings_booking_id"),
        table_name="charging_session_readings",
    )
    op.drop_table("charging_session_readings")
