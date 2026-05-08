"""Add username column to employees and seed test account usernames

Revision ID: h3c4d5e6f7g8
Revises: h2b3c4d5e6f7
Create Date: 2026-05-07

username is the new Cognito sign-in identifier (e.g. danny.rivera).
Auto-generated as firstname.lastname, deduplicated with a numeric suffix.
Nullable now — becomes NOT NULL after the new Cognito pool is live and
all employees have been migrated.
"""
from alembic import op
import sqlalchemy as sa

revision = 'h3c4d5e6f7g8'
down_revision = 'h2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('employees', sa.Column(
        'username', sa.String(100), nullable=True,
    ))
    op.create_index('ix_employees_username', 'employees', ['username'], unique=True)

    # Seed clean usernames for the 8 existing test accounts.
    # Values from the migration plan — see docs/SEED_COMPANY_CONFIG.md.
    op.execute("""
        UPDATE employees SET username = CASE email
            WHEN 'driver@test.com'         THEN 'driver.test'
            WHEN 'walker@test.com'         THEN 'walker.test'
            WHEN 'trainer@test.com'        THEN 'trainer.test'
            WHEN 'trainee@test.com'        THEN 'trainee.test'
            WHEN 'manager@test.com'        THEN 'manager.test'
            WHEN 'dispatch@test.com'       THEN 'dispatch.test'
            WHEN 'asheflow.bot@internal'  THEN 'asheflow.bot'
            WHEN 'test@example.com'        THEN 'test.user'
            ELSE NULL
        END
        WHERE email IN (
            'driver@test.com', 'walker@test.com', 'trainer@test.com',
            'trainee@test.com', 'manager@test.com', 'dispatch@test.com',
            'asheflow.bot@internal', 'test@example.com'
        )
    """)


def downgrade() -> None:
    op.drop_index('ix_employees_username', table_name='employees')
    op.drop_column('employees', 'username')
