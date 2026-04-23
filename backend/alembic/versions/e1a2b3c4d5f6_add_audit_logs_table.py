"""add audit_logs table

Revision ID: e1a2b3c4d5f6
Revises: d3f2a1b4c5e6
Create Date: 2026-04-18

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, None] = 'd3f2a1b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('actor_id',        UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action_type',     sa.String(80),  nullable=False),
        sa.Column('target_table',    sa.String(80),  nullable=False),
        sa.Column('target_id',       UUID(as_uuid=True), nullable=False),
        sa.Column('before_snapshot', JSONB,          nullable=True),
        sa.Column('after_snapshot',  JSONB,          nullable=True),
        sa.Column('created_at',      sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_audit_logs_actor_id',     'audit_logs', ['actor_id'])
    op.create_index('ix_audit_logs_action_type',  'audit_logs', ['action_type'])
    op.create_index('ix_audit_logs_target_table', 'audit_logs', ['target_table'])
    op.create_index('ix_audit_logs_target_id',    'audit_logs', ['target_id'])
    op.create_index('ix_audit_logs_created_at',   'audit_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_created_at',   table_name='audit_logs')
    op.drop_index('ix_audit_logs_target_id',    table_name='audit_logs')
    op.drop_index('ix_audit_logs_target_table', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action_type',  table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_id',     table_name='audit_logs')
    op.drop_table('audit_logs')
