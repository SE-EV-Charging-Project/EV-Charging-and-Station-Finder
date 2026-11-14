"""add durable session stop commands

Revision ID: b6c7d8e9f0a1
Revises: f4a6b8c0d2e4
Create Date: 2026-11-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "f4a6b8c0d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("session_ended_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("session_transaction_id", sa.Integer()))
        batch_op.add_column(sa.Column("meter_stop_wh", sa.Integer()))
        batch_op.add_column(sa.Column("stop_event_idempotency_key", sa.String(length=120)))
        batch_op.create_unique_constraint(
            "uq_bookings_stop_event_idempotency_key",
            ["stop_event_idempotency_key"],
        )

    op.create_table(
        "charging_session_commands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column(
            "trigger",
            sa.Enum(
                "DRIVER",
                "TARGET_ENERGY",
                name="session_stop_command_trigger_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "ACCEPTED",
                "REJECTED",
                "COMPLETED",
                name="session_stop_command_status_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_charging_session_commands_booking_id"),
        "charging_session_commands",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_commands_charger_id"),
        "charging_session_commands",
        ["charger_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_commands_connector_id"),
        "charging_session_commands",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_commands_transaction_id"),
        "charging_session_commands",
        ["transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_commands_status"),
        "charging_session_commands",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_charging_session_commands_status"),
        table_name="charging_session_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_commands_transaction_id"),
        table_name="charging_session_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_commands_connector_id"),
        table_name="charging_session_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_commands_charger_id"),
        table_name="charging_session_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_commands_booking_id"),
        table_name="charging_session_commands",
    )
    op.drop_table("charging_session_commands")

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint(
            "uq_bookings_stop_event_idempotency_key",
            type_="unique",
        )
        batch_op.drop_column("stop_event_idempotency_key")
        batch_op.drop_column("meter_stop_wh")
        batch_op.drop_column("session_transaction_id")
        batch_op.drop_column("session_ended_at")
