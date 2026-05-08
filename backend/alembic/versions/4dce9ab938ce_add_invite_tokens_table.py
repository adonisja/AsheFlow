"""add_invite_tokens_table

Revision ID: 4dce9ab938ce
Revises: h4d5e6f7g8h9
Create Date: 2026-05-08 05:37:43.134382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '4dce9ab938ce'
down_revision: Union[str, None] = 'h4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invite_tokens',
        sa.Column('id',          sa.UUID(), nullable=False),
        sa.Column('token',       sa.String(64), nullable=False),
        sa.Column('company_id',  sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('created_at',  sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at',  sa.DateTime(timezone=True), nullable=False),
        sa.Column('used',        sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token',       name='uq_invite_tokens_token'),
        sa.UniqueConstraint('employee_id', name='uq_invite_tokens_employee_id'),
    )
    op.create_index('ix_invite_tokens_token',      'invite_tokens', ['token'],      unique=True)
    op.create_index('ix_invite_tokens_company_id', 'invite_tokens', ['company_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_invite_tokens_company_id', table_name='invite_tokens')
    op.drop_index('ix_invite_tokens_token',      table_name='invite_tokens')
    op.drop_table('invite_tokens')
