"""delivery_stops table and delivery_stop_id FK on rts_packages and missing_packages

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-06-25

ADR-143: Per-address stop completion tracking with RTS linkage.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision    = 'n7o8p9q0r1s2'
down_revision = 'm6n7o8p9q0r1'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'delivery_stops',
        sa.Column('id',                  postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id',          postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('route_id',            postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('truck_assignment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('walker_id',           postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('walker_name',         sa.String(100), nullable=True),
        sa.Column('normalised_address',  sa.String(200), nullable=False),
        sa.Column('block_key',           sa.String(100), nullable=False),
        sa.Column('tba_numbers',         postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('completed_at',        sa.DateTime(timezone=True), nullable=False),
        sa.Column('stop_sequence',       sa.Integer(), nullable=False),
        sa.Column('packages_total',      sa.Integer(), nullable=False),
        sa.Column('packages_delivered',  sa.Integer(), nullable=False),
        sa.Column('rts_count',           sa.Integer(), nullable=False, server_default='0'),
        sa.Column('missing_count',       sa.Integer(), nullable=False, server_default='0'),
        sa.Column('effort_class',        sa.String(20), nullable=False),
        sa.Column('workload_class',      sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(['route_id'],            ['routes.id'],            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['truck_assignment_id'], ['truck_assignments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['walker_id'],           ['employees.id'],         ondelete='SET NULL'),
        sa.UniqueConstraint('route_id', 'normalised_address', name='uq_delivery_stops_route_address'),
    )
    op.create_index('ix_delivery_stops_company_id',             'delivery_stops', ['company_id'])
    op.create_index('ix_delivery_stops_company_route',          'delivery_stops', ['company_id', 'route_id'])
    op.create_index('ix_delivery_stops_company_walker_time',    'delivery_stops', ['company_id', 'walker_id', 'completed_at'])

    op.add_column('rts_packages',     sa.Column('delivery_stop_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('missing_packages', sa.Column('delivery_stop_id', postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key(
        'fk_rts_packages_delivery_stop',
        'rts_packages', 'delivery_stops',
        ['delivery_stop_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_missing_packages_delivery_stop',
        'missing_packages', 'delivery_stops',
        ['delivery_stop_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_missing_packages_delivery_stop', 'missing_packages', type_='foreignkey')
    op.drop_constraint('fk_rts_packages_delivery_stop',     'rts_packages',     type_='foreignkey')
    op.drop_column('missing_packages', 'delivery_stop_id')
    op.drop_column('rts_packages',     'delivery_stop_id')
    op.drop_index('ix_delivery_stops_company_walker_time', table_name='delivery_stops')
    op.drop_index('ix_delivery_stops_company_route',       table_name='delivery_stops')
    op.drop_index('ix_delivery_stops_company_id',          table_name='delivery_stops')
    op.drop_table('delivery_stops')
