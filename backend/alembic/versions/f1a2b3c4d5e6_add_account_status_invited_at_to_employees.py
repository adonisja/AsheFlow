"""add account_status and invited_at to employees

Revision ID: f1a2b3c4d5e6
Revises: e1a2b3c4d5f6
Create Date: 2026-04-18

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add account_status — existing rows are all real active employees, so default to 'active'
    op.add_column('employees', sa.Column(
        'account_status',
        sa.String(30),
        nullable=False,
        server_default='active',
    ))
    op.create_check_constraint(
        'ck_employees_account_status_valid',
        'employees',
        "account_status IN ('pending_verification', 'active', 'deactivated')",
    )
    op.create_index('ix_employees_account_status', 'employees', ['account_status'])

    # Add invited_at — nullable, only populated for new invites going forward
    op.add_column('employees', sa.Column(
        'invited_at',
        sa.DateTime(timezone=True),
        nullable=True,
    ))

    # Flip is_active default to False — new invites start inactive until first login
    op.alter_column('employees', 'is_active', server_default=sa.text('false'))


def downgrade() -> None:
    op.alter_column('employees', 'is_active', server_default=sa.text('true'))
    op.drop_column('employees', 'invited_at')
    op.drop_index('ix_employees_account_status', table_name='employees')
    op.drop_constraint('ck_employees_account_status_valid', 'employees', type_='check')
    op.drop_column('employees', 'account_status')
