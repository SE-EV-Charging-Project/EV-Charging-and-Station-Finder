"""add driver profile preferences to users table

Revision ID: 8db1f6274856
Revises: a07d9695d686
Create Date: 2026-11-01 15:13:08.036955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8db1f6274856'
down_revision: Union[str, Sequence[str], None] = 'a07d9695d686'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('default_charging_mode', sa.Enum('FASTEST', 'CHEAPEST', 'NEAREST', name='charging_mode_enum', native_enum=False), nullable=False, server_default='FASTEST'))
        batch_op.add_column(sa.Column('default_target_battery', sa.Integer(), nullable=False, server_default='80'))
        batch_op.add_column(sa.Column('low_battery_threshold', sa.Integer(), nullable=False, server_default='20'))
        batch_op.add_column(sa.Column('default_search_radius', sa.Integer(), nullable=False, server_default='10'))
        batch_op.add_column(sa.Column('notify_email', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('notify_sms', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('notify_push', sa.Boolean(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('notify_push')
        batch_op.drop_column('notify_sms')
        batch_op.drop_column('notify_email')
        batch_op.drop_column('default_search_radius')
        batch_op.drop_column('low_battery_threshold')
        batch_op.drop_column('default_target_battery')
        batch_op.drop_column('default_charging_mode')
