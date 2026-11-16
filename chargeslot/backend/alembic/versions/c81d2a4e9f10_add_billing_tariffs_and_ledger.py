"""add billing tariffs and payment ledger

Revision ID: c81d2a4e9f10
Revises: 51913605688c
Create Date: 2026-11-15 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c81d2a4e9f10"
down_revision: Union[str, Sequence[str], None] = "51913605688c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "station_tariffs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("price_per_kwh", sa.Float(), nullable=False),
        sa.Column("idle_fee_per_minute", sa.Float(), server_default="0", nullable=False),
        sa.Column("tax_rate_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("peak_periods", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_station_tariffs_station_id", "station_tariffs", ["station_id"], unique=False
    )
    op.create_index(
        "ix_station_tariffs_effective_from",
        "station_tariffs",
        ["effective_from"],
        unique=False,
    )

    op.add_column("bookings", sa.Column("tariff_snapshot_id", sa.Integer(), nullable=True))
    op.add_column(
        "bookings",
        sa.Column("tariff_price_per_kwh", sa.Float(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("tariff_idle_fee_per_minute", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("tariff_tax_rate_percent", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("tariff_peak_periods", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("reservation_fee_paid_amount", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("energy_delivered_kwh", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("energy_cost_amount", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("idle_fee_amount", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("tax_amount", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("final_bill_amount", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("payment_due", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.create_foreign_key(
            "fk_bookings_tariff_snapshot_id_station_tariffs",
            "station_tariffs",
            ["tariff_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_bookings_payment_due", "bookings", ["payment_due"], unique=False)

    op.create_table(
        "payment_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("refund_of_id", sa.Integer(), nullable=True),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("payment_type", sa.String(length=30), nullable=False),
        sa.Column("gateway", sa.String(length=30), server_default="razorpay", nullable=False),
        sa.Column("gateway_reference", sa.String(length=255), nullable=True),
        sa.Column("gateway_payment_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("refund_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["refund_of_id"], ["payment_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payment_records_user_idempotency_key"),
    )
    op.create_index("ix_payment_records_user_id", "payment_records", ["user_id"], unique=False)
    op.create_index("ix_payment_records_booking_id", "payment_records", ["booking_id"], unique=False)
    op.create_index(
        "ix_payment_records_gateway_reference",
        "payment_records",
        ["gateway_reference"],
        unique=True,
    )
    op.create_index(
        "ix_payment_records_gateway_payment_id",
        "payment_records",
        ["gateway_payment_id"],
        unique=True,
    )
    op.create_index("ix_payment_records_created_at", "payment_records", ["created_at"], unique=False)

    op.create_table(
        "payment_reconciliations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reconciled_on", sa.String(length=10), nullable=False),
        sa.Column("gateway_payment_count", sa.Integer(), nullable=False),
        sa.Column("internal_payment_count", sa.Integer(), nullable=False),
        sa.Column("discrepancies", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reconciled_on"),
    )

    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("analytics_snapshots")
    op.drop_table("payment_reconciliations")
    op.drop_index("ix_payment_records_created_at", table_name="payment_records")
    op.drop_index("ix_payment_records_gateway_payment_id", table_name="payment_records")
    op.drop_index("ix_payment_records_gateway_reference", table_name="payment_records")
    op.drop_index("ix_payment_records_booking_id", table_name="payment_records")
    op.drop_index("ix_payment_records_user_id", table_name="payment_records")
    op.drop_table("payment_records")
    op.drop_index("ix_bookings_payment_due", table_name="bookings")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint(
            "fk_bookings_tariff_snapshot_id_station_tariffs", type_="foreignkey"
        )
    for column in (
        "payment_due",
        "final_bill_amount",
        "tax_amount",
        "idle_fee_amount",
        "energy_cost_amount",
        "energy_delivered_kwh",
        "reservation_fee_paid_amount",
        "tariff_peak_periods",
        "tariff_tax_rate_percent",
        "tariff_idle_fee_per_minute",
        "tariff_price_per_kwh",
        "tariff_snapshot_id",
    ):
        op.drop_column("bookings", column)
    op.drop_index("ix_station_tariffs_effective_from", table_name="station_tariffs")
    op.drop_index("ix_station_tariffs_station_id", table_name="station_tariffs")
    op.drop_table("station_tariffs")
