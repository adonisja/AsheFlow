"""add sort lock fields to truck_assignments

Revision ID: a1b2c3d4e5f8
Revises: z3a4b5c6d7e8
Create Date: 2026-05-30

Adds two nullable columns to truck_assignments that track which trainer
initiated the walker route sort and when.  Null means the sort has not yet
been committed for that assignment.  The commit_sort endpoint sets these
atomically and rejects a second commit attempt (409 Conflict) so that only
one trainer per truck per day can run the sort.
"""

from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f8'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'truck_assignments',
        sa.Column(
            'sort_initiated_by',
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey('employees.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'truck_assignments',
        sa.Column(
            'sort_committed_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_truck_assignments_sort_initiated_by',
        'truck_assignments',
        ['sort_initiated_by'],
    )


def downgrade() -> None:
    op.drop_index('ix_truck_assignments_sort_initiated_by', table_name='truck_assignments')
    op.drop_column('truck_assignments', 'sort_committed_at')
    op.drop_column('truck_assignments', 'sort_initiated_by')
