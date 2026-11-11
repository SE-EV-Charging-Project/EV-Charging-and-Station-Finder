"""create faulty charger reports table

Revision ID: e1f6a2b3c4d5
Revises: d9e5f0a1b2c4
Create Date: 2026-11-11 14:58:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f6a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d9e5f0a1b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "faulty_charger_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reporter_user_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("charger_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=True),
        sa.Column(
            "fault_type",
            sa.Enum(
                "HARDWARE_FAULT",
                "CONNECTOR_DAMAGE",
                "POWER_FAILURE",
                "CABLE_DAMAGE",
                "SCREEN_ISSUE",
                "OFFLINE",
                "OTHER",
                name="fault_type_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="fault_severity_enum", native_enum=False),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "FORWARDED",
                "ACKNOWLEDGED",
                "RESOLVED",
                name="fault_report_status_enum",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forwarded_channels", sa.String(length=100), nullable=False),
        sa.Column("forwarded_to_email", sa.String(length=120), nullable=True),
        sa.Column("forwarded_to_phone", sa.String(length=20), nullable=True),
        sa.Column("operator_notes", sa.String(length=500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["charger_id"], ["chargers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_faulty_charger_reports_charger_id"), "faulty_charger_reports", ["charger_id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_connector_id"), "faulty_charger_reports", ["connector_id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_id"), "faulty_charger_reports", ["id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_operator_id"), "faulty_charger_reports", ["operator_id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_reporter_user_id"), "faulty_charger_reports", ["reporter_user_id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_station_id"), "faulty_charger_reports", ["station_id"], unique=False)
    op.create_index(op.f("ix_faulty_charger_reports_status"), "faulty_charger_reports", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_faulty_charger_reports_status"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_station_id"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_reporter_user_id"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_operator_id"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_id"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_connector_id"), table_name="faulty_charger_reports")
    op.drop_index(op.f("ix_faulty_charger_reports_charger_id"), table_name="faulty_charger_reports")
    op.drop_table("faulty_charger_reports")

