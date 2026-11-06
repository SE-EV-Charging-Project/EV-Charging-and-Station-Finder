"""add charger out of service fields

Revision ID: a187d925e01c
Revises: 83a1b42c67ef
Create Date: 2026-11-06 16:16:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a187d925e01c'
down_revision: Union[str, Sequence[str], None] = '83a1b42c67ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add out of service fields to chargers table."""
    with op.batch_alter_table('chargers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('out_of_service_reason', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('expected_return_time', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('out_of_service_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema: remove out of service fields from chargers table."""
    with op.batch_alter_table('chargers', schema=None) as batch_op:
        batch_op.drop_column('out_of_service_at')
        batch_op.drop_column('expected_return_time')
        batch_op.drop_column('out_of_service_reason')
