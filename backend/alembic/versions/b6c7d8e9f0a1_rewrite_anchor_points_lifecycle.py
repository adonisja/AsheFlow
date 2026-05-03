"""rewrite anchor_points for full shift lifecycle

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-02

Drops the single-record-per-truck-per-day constraint and replaces it with a
multi-AP-per-day model that tracks preliminary → arrived → relocated status.

Changes:
- Drop UniqueConstraint uq_anchor_points_truck_date
- Add columns: sequence (int), is_initial (bool), status (varchar 20), arrived_at (timestamptz)
- Backfill existing rows: sequence=1, is_initial=true, status=arrived (they were confirmed EOD)
- Add CheckConstraint on status values
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uq_anchor_points_truck_date', 'anchor_points', type_='unique')

    op.add_column('anchor_points', sa.Column('sequence',   sa.Integer(),     nullable=False, server_default='1'))
    op.add_column('anchor_points', sa.Column('is_initial', sa.Boolean(),     nullable=False, server_default='true'))
    op.add_column('anchor_points', sa.Column('status',     sa.String(20),    nullable=False, server_default='arrived'))
    op.add_column('anchor_points', sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill arrived_at from confirmed_at for existing records
    op.execute("UPDATE anchor_points SET arrived_at = confirmed_at WHERE confirmed_at IS NOT NULL")
    op.execute("UPDATE anchor_points SET arrived_at = submitted_at WHERE arrived_at IS NULL")

    op.create_check_constraint(
        'ck_anchor_points_status',
        'anchor_points',
        "status IN ('preliminary','arrived','relocated')",
    )

    # Drop server defaults now that backfill is done — app layer sets these
    op.alter_column('anchor_points', 'sequence',   server_default=None)
    op.alter_column('anchor_points', 'is_initial', server_default=None)
    op.alter_column('anchor_points', 'status',     server_default=None)


def downgrade() -> None:
    op.drop_constraint('ck_anchor_points_status', 'anchor_points', type_='check')
    op.drop_column('anchor_points', 'arrived_at')
    op.drop_column('anchor_points', 'status')
    op.drop_column('anchor_points', 'is_initial')
    op.drop_column('anchor_points', 'sequence')
    op.create_unique_constraint('uq_anchor_points_truck_date', 'anchor_points', ['truck_id', 'date'])
