"""add truck anchor fields

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('trucks', sa.Column('initial_anchor_address', sa.String(300), nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor_lat',     sa.Float(),      nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor_lng',     sa.Float(),      nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor_set_by',  postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('trucks', sa.Column('initial_anchor_set_at',  sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_trucks_anchor_set_by_employees',
        'trucks', 'employees',
        ['initial_anchor_set_by'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_trucks_anchor_set_by_employees', 'trucks', type_='foreignkey')
    op.drop_column('trucks', 'initial_anchor_set_at')
    op.drop_column('trucks', 'initial_anchor_set_by')
    op.drop_column('trucks', 'initial_anchor_lng')
    op.drop_column('trucks', 'initial_anchor_lat')
    op.drop_column('trucks', 'initial_anchor_address')
