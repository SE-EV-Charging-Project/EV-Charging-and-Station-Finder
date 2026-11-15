"""add check-in timestamp and durable remote-start commands

Revision ID: d3e4f5a6b7c8
Revises: c8d9e0f1a2b3
Create Date: 2026-11-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("checked_in_at", sa.DateTime(timezone=True)))

    op.create_table(
        "charging_session_start_commands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("start_event_idempotency_key", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "ACCEPTED",
                "REJECTED",
                "STARTED",
                "FAILED",
                name="session_start_command_status_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_charging_session_start_commands_idempotency_key",
        ),
        sa.UniqueConstraint(
            "start_event_idempotency_key",
            name="uq_charging_session_start_commands_start_event_key",
        ),
    )
    op.create_index(
        op.f("ix_charging_session_start_commands_booking_id"),
        "charging_session_start_commands",
        ["booking_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_start_commands_charger_id"),
        "charging_session_start_commands",
        ["charger_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_start_commands_connector_id"),
        "charging_session_start_commands",
        ["connector_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_session_start_commands_status"),
        "charging_session_start_commands",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_charging_session_start_commands_status"),
        table_name="charging_session_start_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_start_commands_connector_id"),
        table_name="charging_session_start_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_start_commands_charger_id"),
        table_name="charging_session_start_commands",
    )
    op.drop_index(
        op.f("ix_charging_session_start_commands_booking_id"),
        table_name="charging_session_start_commands",
    )
    op.drop_table("charging_session_start_commands")

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("checked_in_at")
