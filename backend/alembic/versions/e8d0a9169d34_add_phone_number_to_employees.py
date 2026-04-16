"""add_phone_number_to_employees

Revision ID: e8d0a9169d34
Revises: dd69d9df05d9
Create Date: 2026-04-11 06:35:43.584113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8d0a9169d34'
down_revision: Union[str, Sequence[str], None] = 'dd69d9df05d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('phone_number', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('employees', 'phone_number')
