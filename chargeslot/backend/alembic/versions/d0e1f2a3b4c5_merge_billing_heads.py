"""merge billing and booking payment migration heads

Revision ID: d0e1f2a3b4c5
Revises: c81d2a4e9f10, c8d9e0f1a2b3
Create Date: 2026-11-16 00:00:00.000000

"""
from typing import Sequence, Union


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = (
    "c81d2a4e9f10",
    "c8d9e0f1a2b3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
