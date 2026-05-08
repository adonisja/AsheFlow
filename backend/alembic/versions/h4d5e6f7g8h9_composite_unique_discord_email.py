"""Replace global unique constraints on discord_id and email with composite (company_id, field)

Revision ID: h4d5e6f7g8h9
Revises: h3c4d5e6f7g8
Create Date: 2026-05-07

discord_id and email were globally unique, which prevents the same Discord
user or email from existing across two different companies. The correct
constraint is uniqueness within a company, not across the entire table.
"""
from alembic import op

revision = 'h4d5e6f7g8h9'
down_revision = 'h3c4d5e6f7g8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── discord_id ────────────────────────────────────────────────────────────
    op.drop_index('ix_employees_discord_id', table_name='employees')
    op.create_index(
        'uq_employees_company_discord_id',
        'employees', ['company_id', 'discord_id'],
        unique=True,
    )

    # ── email ─────────────────────────────────────────────────────────────────
    op.drop_index('ix_employees_email', table_name='employees')
    op.create_index(
        'uq_employees_company_email',
        'employees', ['company_id', 'email'],
        unique=True,
        postgresql_where='email IS NOT NULL',  # exclude NULL emails from uniqueness check
    )


def downgrade() -> None:
    op.drop_index('uq_employees_company_email',     table_name='employees')
    op.drop_index('uq_employees_company_discord_id', table_name='employees')

    op.create_index('ix_employees_email',      'employees', ['email'],      unique=True)
    op.create_index('ix_employees_discord_id', 'employees', ['discord_id'], unique=True)
