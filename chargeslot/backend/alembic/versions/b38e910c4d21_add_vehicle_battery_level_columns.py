"""add vehicle battery level columns

Revision ID: b38e910c4d21
Revises: a187d925e01c
Create Date: 2026-11-10 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b38e910c4d21'
down_revision: Union[str, Sequence[str], None] = 'a187d925e01c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add current_soc, target_soc, and battery_updated_at to vehicles table."""
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('current_soc', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('target_soc', sa.Integer(), nullable=False, server_default='80'))
        batch_op.add_column(sa.Column('battery_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema: remove battery fields from vehicles table."""
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.drop_column('battery_updated_at')
        batch_op.drop_column('target_soc')
        batch_op.drop_column('current_soc')
