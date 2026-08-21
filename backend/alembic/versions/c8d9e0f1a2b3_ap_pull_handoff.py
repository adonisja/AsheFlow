"""add AP-pull walker->driver handoff columns to package_removals

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-03

ADR-178: out-of-zone rider packages are found by the WALKER whose route owns
the tote and handed to the driver via a two-party confirmation. anchor_point
removals gain a handoff lifecycle (pending -> handed_over -> received).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('package_removals', sa.Column('handoff_status', sa.String(20), nullable=False, server_default='pending'))
    op.add_column('package_removals', sa.Column('handed_over_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True))
    op.add_column('package_removals', sa.Column('handed_over_by_name', sa.String(100), nullable=True))
    op.add_column('package_removals', sa.Column('handed_over_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('package_removals', sa.Column('received_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True))
    op.add_column('package_removals', sa.Column('received_by_name', sa.String(100), nullable=True))
    op.add_column('package_removals', sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ('received_at', 'received_by_name', 'received_by', 'handed_over_at',
                'handed_over_by_name', 'handed_over_by', 'handoff_status'):
        op.drop_column('package_removals', col)
