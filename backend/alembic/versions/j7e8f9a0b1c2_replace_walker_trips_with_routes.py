"""replace walker_trips with routes table; repurpose walker_routes as daily summary

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
Create Date: 2026-06-02

ADR-118: Route is the atomic unit (one cart trip, geographic identity preserved).
WalkerTrip is dropped. WalkerRoute is repurposed from a person-centric route
container to a daily summary aggregate. Routes are computed independently of
person assignment — wave distribution assigns people to routes as a second step.

Schema changes:
  - DROP TABLE walker_trips
  - ADD COLUMNS to walker_routes (repurpose as daily summary)
  - CREATE TABLE routes
  - CREATE TABLE route_cluster_centroids (density map support)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = 'j7e8f9a0b1c2'
down_revision = 'i6d7e8f9a0b1'
branch_labels = None
depends_on = None


def upgrade():
    # ── Drop walker_trips ──────────────────────────────────────────────────
    op.drop_table('walker_trips')

    # ── Repurpose walker_routes as daily summary ───────────────────────────
    # Remove columns that belonged to the old route-container model
    op.drop_column('walker_routes', 'total_ovs')
    op.drop_column('walker_routes', 'planned_trips')
    op.drop_column('walker_routes', 'actual_trips')
    op.drop_column('walker_routes', 'completed_at')

    # Rename walker_id → employee_id (now covers trainers too, not just walkers)
    op.alter_column('walker_routes', 'walker_id', new_column_name='employee_id')

    # Add summary columns
    op.add_column('walker_routes', sa.Column('total_routes', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('walker_routes', sa.Column('total_slot_cost', sa.Integer(), nullable=False, server_default='0'))

    # ── Create routes table ────────────────────────────────────────────────
    op.create_table(
        'routes',
        sa.Column('id',                    UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id',            UUID(as_uuid=True), nullable=False),
        sa.Column('truck_assignment_id',   UUID(as_uuid=True), sa.ForeignKey('truck_assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('route_date',            sa.Date(), nullable=False),
        sa.Column('route_number',          sa.Integer(), nullable=False),

        # Geographic identity — persisted (was discarded in WalkerTrip)
        sa.Column('block_keys',            ARRAY(sa.Text()), nullable=False, server_default='{}'),

        # Tote and package lists
        sa.Column('tote_ids',              ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tba_numbers',           ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tag_numbers',           ARRAY(sa.Text()), nullable=False, server_default='{}'),

        # Capacity — half-slot integer arithmetic (×2 scale)
        sa.Column('slot_cost',             sa.Integer(), nullable=False, default=0),
        sa.Column('capacity_limit',        sa.Integer(), nullable=False),        # base, set at sort time
        sa.Column('capacity_limit_paired', sa.Integer(), nullable=True),         # set at arrival if pair confirmed

        # Effort classification
        sa.Column('effort_class',          sa.String(20), nullable=False, server_default='standard'),  # easy|standard|heavy
        sa.Column('workload_source',       sa.String(20), nullable=False, server_default='default'),   # profile|flag|default

        # Assignment — nullable until wave distribution
        sa.Column('assigned_to',           UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_to_name',      sa.String(100), nullable=True),

        # Trainer+trainee pairing
        sa.Column('paired_trainee_id',     UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('trainee_phase',         sa.Integer(), nullable=True),          # 1-5
        sa.Column('phase4_solo_opted_in',  sa.Boolean(), nullable=False, server_default='false'),

        # Status lifecycle
        sa.Column('status',                sa.String(20), nullable=False, server_default='unassigned'),  # unassigned|assigned|in_progress|completed
        sa.Column('departed_at',           sa.DateTime(timezone=True), nullable=True),
        sa.Column('returned_at',           sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',            sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_index('ix_routes_company_id',           'routes', ['company_id'])
    op.create_index('ix_routes_truck_assignment_id',  'routes', ['truck_assignment_id'])
    op.create_index('ix_routes_route_date',           'routes', ['route_date'])
    op.create_index('ix_routes_assigned_to',          'routes', ['assigned_to'])
    op.create_index('ix_routes_company_date',         'routes', ['company_id', 'route_date'])

    # Unique: one route_number per truck_assignment
    op.create_unique_constraint(
        'uq_routes_assignment_number',
        'routes',
        ['truck_assignment_id', 'route_number'],
    )

    # ── Create route_cluster_centroids (density map support) ───────────────
    op.create_table(
        'route_cluster_centroids',
        sa.Column('id',                  UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id',          UUID(as_uuid=True), nullable=False),
        sa.Column('truck_assignment_id', UUID(as_uuid=True), sa.ForeignKey('truck_assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('route_date',          sa.Date(), nullable=False),
        sa.Column('centroid_lat',        sa.Float(), nullable=False),
        sa.Column('centroid_lng',        sa.Float(), nullable=False),
        sa.Column('package_count',       sa.Integer(), nullable=False),
        sa.Column('truck_zone_label',    sa.String(50), nullable=True),
    )

    op.create_index('ix_rcc_company_date', 'route_cluster_centroids', ['company_id', 'route_date'])
    op.create_index('ix_rcc_truck_assignment_id', 'route_cluster_centroids', ['truck_assignment_id'])


def downgrade():
    op.drop_table('route_cluster_centroids')
    op.drop_table('routes')

    # Reverse walker_routes repurposing
    op.drop_column('walker_routes', 'total_slot_cost')
    op.drop_column('walker_routes', 'total_routes')
    op.alter_column('walker_routes', 'employee_id', new_column_name='walker_id')
    op.add_column('walker_routes', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('walker_routes', sa.Column('actual_trips', sa.Integer(), nullable=True))
    op.add_column('walker_routes', sa.Column('planned_trips', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('walker_routes', sa.Column('total_ovs', sa.Integer(), nullable=False, server_default='0'))

    # Recreate walker_trips
    op.create_table(
        'walker_trips',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id',      UUID(as_uuid=True), nullable=False),
        sa.Column('walker_route_id', UUID(as_uuid=True), sa.ForeignKey('walker_routes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trip_number',     sa.Integer(), nullable=False),
        sa.Column('bag_ids',         ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tba_numbers',     ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tag_numbers',     ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('status',          sa.String(20), nullable=False, server_default='pending'),
        sa.Column('departed_at',     sa.DateTime(timezone=True), nullable=True),
        sa.Column('returned_at',     sa.DateTime(timezone=True), nullable=True),
    )
