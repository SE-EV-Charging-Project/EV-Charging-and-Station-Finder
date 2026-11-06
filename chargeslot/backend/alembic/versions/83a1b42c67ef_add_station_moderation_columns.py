"""add station moderation columns

Revision ID: 83a1b42c67ef
Revises: 7142ac351777
Create Date: 2026-11-06 16:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83a1b42c67ef'
down_revision: Union[str, Sequence[str], None] = '7142ac351777'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add moderation fields to stations table."""
    with op.batch_alter_table('stations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rejection_reason', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_admin_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            'fk_stations_reviewed_by_admin_id',
            'users',
            ['reviewed_by_admin_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade() -> None:
    """Downgrade schema: remove moderation fields from stations table."""
    with op.batch_alter_table('stations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stations_reviewed_by_admin_id', type_='foreignkey')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by_admin_id')
        batch_op.drop_column('rejection_reason')
