"""add vehicle overlap slot claims

Revision ID: d2e3f4a5b6c7
Revises: b7c6d5e4f3a2
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "b7c6d5e4f3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("booking_slot_claims") as batch_op:
        batch_op.add_column(sa.Column("vehicle_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_booking_slot_claims_vehicle_id_vehicles",
            "vehicles",
            ["vehicle_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_booking_slot_claim_vehicle_start",
            ["vehicle_id", "slot_start_time"],
        )
    op.create_index(
        op.f("ix_booking_slot_claims_vehicle_id"),
        "booking_slot_claims",
        ["vehicle_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_booking_slot_claims_vehicle_id"),
        table_name="booking_slot_claims",
    )
    with op.batch_alter_table("booking_slot_claims") as batch_op:
        batch_op.drop_constraint(
            "uq_booking_slot_claim_vehicle_start",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_booking_slot_claims_vehicle_id_vehicles",
            type_="foreignkey",
        )
        batch_op.drop_column("vehicle_id")
