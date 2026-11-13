"""merge battery and booking migration heads

Revision ID: c4d5e6f7a8b9
Revises: a9b8c7d6e5f4, b38e910c4d21
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = (
    "a9b8c7d6e5f4",
    "b38e910c4d21",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
