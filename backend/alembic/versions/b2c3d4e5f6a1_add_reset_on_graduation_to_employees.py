"""add_reset_on_graduation_to_employees

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 01:00:00.000000

Adds reset_on_graduation boolean to employees table.
When True, graduation does not promote to walker — instead the
employee is reset to trainee at Phase 1 (training records cleared).
Used for trainees enrolled in a simulation/demo cycle.
"""

from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'employees',
        sa.Column('reset_on_graduation', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade():
    op.drop_column('employees', 'reset_on_graduation')
