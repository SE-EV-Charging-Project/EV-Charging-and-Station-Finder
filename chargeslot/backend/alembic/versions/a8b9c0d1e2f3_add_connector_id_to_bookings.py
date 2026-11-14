"""add connector_id to bookings

Revision ID: a8b9c0d1e2f3
Revises: f2a7b3c4d5e6
Create Date: 2026-11-14 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add optional connector_id to bookings table."""
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connector_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_bookings_connector_id_connectors",
            "connectors",
            ["connector_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_bookings_connector_id",
            ["connector_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema: remove connector_id from bookings table."""
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.drop_index("ix_bookings_connector_id")
        batch_op.drop_constraint("fk_bookings_connector_id_connectors", type_="foreignkey")
        batch_op.drop_column("connector_id")
