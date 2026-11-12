"""add_price_per_kwh_to_stations

Revision ID: a77db63a057c
Revises: b391c45d820f
Create Date: 2026-11-10 20:41:07.250745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a77db63a057c'
down_revision: Union[str, Sequence[str], None] = 'b391c45d820f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stations', sa.Column('price_per_kwh', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('stations', 'price_per_kwh')
