"""create favourite stations table

Revision ID: c8d4e9f1a2b3
Revises: a77db63a057c
Create Date: 2026-11-11 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8d4e9f1a2b3"
down_revision: Union[str, Sequence[str], None] = "a77db63a057c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "favourite_stations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "station_id",
            name="uq_favourite_stations_user_station",
        ),
    )
    op.create_index(op.f("ix_favourite_stations_id"), "favourite_stations", ["id"], unique=False)
    op.create_index(op.f("ix_favourite_stations_station_id"), "favourite_stations", ["station_id"], unique=False)
    op.create_index(op.f("ix_favourite_stations_user_id"), "favourite_stations", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_favourite_stations_user_id"), table_name="favourite_stations")
    op.drop_index(op.f("ix_favourite_stations_station_id"), table_name="favourite_stations")
    op.drop_index(op.f("ix_favourite_stations_id"), table_name="favourite_stations")
    op.drop_table("favourite_stations")

