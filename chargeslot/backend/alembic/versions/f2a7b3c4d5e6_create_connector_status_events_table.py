"""create connector status events table

Revision ID: f2a7b3c4d5e6
Revises: e1f6a2b3c4d5
Create Date: 2026-11-11 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a7b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e1f6a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "connector_status_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("gateway_id", sa.String(length=100), nullable=False),
        sa.Column(
            "previous_status",
            sa.Enum(
                "AVAILABLE",
                "OCCUPIED",
                "RESERVED",
                "FAULTED",
                "OFFLINE",
                name="connector_status_enum",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "new_status",
            sa.Enum(
                "AVAILABLE",
                "OCCUPIED",
                "RESERVED",
                "FAULTED",
                "OFFLINE",
                name="connector_status_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("raw_status", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_connector_status_events_idempotency_key"),
    )
    op.create_index(op.f("ix_connector_status_events_charger_id"), "connector_status_events", ["charger_id"], unique=False)
    op.create_index(op.f("ix_connector_status_events_connector_id"), "connector_status_events", ["connector_id"], unique=False)
    op.create_index(op.f("ix_connector_status_events_gateway_id"), "connector_status_events", ["gateway_id"], unique=False)
    op.create_index(op.f("ix_connector_status_events_id"), "connector_status_events", ["id"], unique=False)
    op.create_index(op.f("ix_connector_status_events_idempotency_key"), "connector_status_events", ["idempotency_key"], unique=True)
    op.create_index(op.f("ix_connector_status_events_new_status"), "connector_status_events", ["new_status"], unique=False)
    op.create_index(op.f("ix_connector_status_events_observed_at"), "connector_status_events", ["observed_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_connector_status_events_observed_at"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_new_status"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_idempotency_key"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_id"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_gateway_id"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_connector_id"), table_name="connector_status_events")
    op.drop_index(op.f("ix_connector_status_events_charger_id"), table_name="connector_status_events")
    op.drop_table("connector_status_events")

