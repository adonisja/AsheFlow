"""add hr_system_id_adp and hr_system_id_adp_verified to employees

Revision ID: u8v9w0x1y2z3
Revises: t7u8v9w0x1y2
Create Date: 2026-05-27

Adds two columns to the employees table:
  - hr_system_id_adp: ADP associateOID. NOT NULL — backfilled with gen_random_uuid()
    for all pre-existing rows. Real ADP IDs are populated at CSV import time.
  - hr_system_id_adp_verified: boolean, default false. Flips to true on first
    successful GET /hr/v2/workers round-trip that confirms the stored ID resolves
    to a live ADP worker record (triggered by company ADP OAuth connection).

Timecard sync (sync_adp_timecards.py) only runs for employees where
hr_system_id_adp_verified = true.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = 'u8v9w0x1y2z3'
down_revision = 't7u8v9w0x1y2'
branch_labels = None
depends_on = None


def upgrade():
    # Add as nullable first so the backfill can run before enforcing NOT NULL
    op.add_column('employees',
        sa.Column('hr_system_id_adp', UUID(as_uuid=True), nullable=True)
    )
    op.add_column('employees',
        sa.Column('hr_system_id_adp_verified', sa.Boolean(),
                  server_default='false', nullable=False)
    )

    # Backfill all existing rows with a generated UUID placeholder
    op.execute("UPDATE employees SET hr_system_id_adp = gen_random_uuid() WHERE hr_system_id_adp IS NULL")

    # Now enforce NOT NULL
    op.alter_column('employees', 'hr_system_id_adp', nullable=False)


def downgrade():
    op.drop_column('employees', 'hr_system_id_adp_verified')
    op.drop_column('employees', 'hr_system_id_adp')
