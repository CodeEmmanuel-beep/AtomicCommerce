"""merged heads

Revision ID: 0820355a0cac
Revises: 49c5feb1a8e1, 6e1bb2f345c3
Create Date: 2026-10-01 15:47:48.986937

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0820355a0cac'
down_revision: Union[str, Sequence[str], None] = ('49c5feb1a8e1', '6e1bb2f345c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
