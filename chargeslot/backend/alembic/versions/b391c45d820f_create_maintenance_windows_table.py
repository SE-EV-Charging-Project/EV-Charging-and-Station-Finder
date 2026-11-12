"""create maintenance windows table

Revision ID: b391c45d820f
Revises: a187d925e01c
Create Date: 2026-11-06 20:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b391c45d820f'
down_revision: Union[str, Sequence[str], None] = 'a187d925e01c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'maintenance_windows',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('station_id', sa.Integer(), nullable=False),
        sa.Column('charger_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['charger_id'], ['chargers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_maintenance_windows_id'), 'maintenance_windows', ['id'], unique=False)
    op.create_index(op.f('ix_maintenance_windows_station_id'), 'maintenance_windows', ['station_id'], unique=False)
    op.create_index(op.f('ix_maintenance_windows_charger_id'), 'maintenance_windows', ['charger_id'], unique=False)
    op.create_index(op.f('ix_maintenance_windows_start_time'), 'maintenance_windows', ['start_time'], unique=False)
    op.create_index(op.f('ix_maintenance_windows_end_time'), 'maintenance_windows', ['end_time'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_maintenance_windows_end_time'), table_name='maintenance_windows')
    op.drop_index(op.f('ix_maintenance_windows_start_time'), table_name='maintenance_windows')
    op.drop_index(op.f('ix_maintenance_windows_charger_id'), table_name='maintenance_windows')
    op.drop_index(op.f('ix_maintenance_windows_station_id'), table_name='maintenance_windows')
    op.drop_index(op.f('ix_maintenance_windows_id'), table_name='maintenance_windows')
    op.drop_table('maintenance_windows')

