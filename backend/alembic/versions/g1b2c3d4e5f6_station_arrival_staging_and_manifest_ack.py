"""Add staging fields to station_arrivals and acknowledgement to package_manifests

Revision ID: g1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'g1b2c3d4e5f6'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # station_arrivals: staging check fields (loading arrivals only)
    op.add_column('station_arrivals',
        sa.Column('was_staged', sa.Boolean(), nullable=True))
    op.add_column('station_arrivals',
        sa.Column('missing_items', postgresql.ARRAY(sa.String()), nullable=True))

    # package_manifests: driver acknowledgement
    op.add_column('package_manifests',
        sa.Column('acknowledged_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('package_manifests',
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_package_manifests_acknowledged_by',
        'package_manifests', 'employees',
        ['acknowledged_by'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_package_manifests_acknowledged_by', 'package_manifests', type_='foreignkey')
    op.drop_column('package_manifests', 'acknowledged_at')
    op.drop_column('package_manifests', 'acknowledged_by')
    op.drop_column('station_arrivals', 'missing_items')
    op.drop_column('station_arrivals', 'was_staged')
