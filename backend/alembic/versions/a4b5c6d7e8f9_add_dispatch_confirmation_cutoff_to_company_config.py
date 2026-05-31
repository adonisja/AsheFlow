"""Add dispatch_confirmation_cutoff to company_config.

The cutoff is the local time after which pending dispatch confirmation
notifications are expired and confirmation records are closed.
Defaults to 09:00 — company A's stated deadline.

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4b5c6d7e8f9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'company_configs',
        sa.Column(
            'dispatch_confirmation_cutoff',
            sa.Time(),
            nullable=True,
            comment='Local time after which pending confirmation notifications expire (default 09:00)',
        ),
    )


def downgrade() -> None:
    op.drop_column('company_configs', 'dispatch_confirmation_cutoff')
