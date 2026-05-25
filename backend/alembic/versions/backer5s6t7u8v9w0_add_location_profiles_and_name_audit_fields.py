"""add location_profiles table and _name audit fields to existing tables

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-05-24
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from typing import Sequence, Union

# Revision identifiers
revision: str = 'r5s6t7u8v9w0'
down_revision: Union[str, Sequence[str], None] = 'q4r5s6t7u8v9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """ Upgrade schema """
    op.create_table("location_profiles",
        # Identity records - What the record describes
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('block_key', sa.String(length=60), nullable=False),
        sa.Column('building_type', sa.String(length=30), nullable=False),
        sa.Column('workload_class', sa.String(length=20), nullable=False),
        

        # Building type lifecycle - the locking/verification flow
        sa.Column('building_type_status', sa.String(length=20), server_default='pending'),
        sa.Column('building_type_agreement_count', sa.Integer(), server_default="0"),

        # Notes lifecycle - the separate note verification flow
        sa.Column('raw_notes', sa.Text, nullable=True),
        sa.Column('operational_note', sa.Text(), nullable=True),
        sa.Column('note_verified', sa.Boolean, server_default='false'),
        sa.Column('note_verified_by', sa.UUID(), nullable=True),
        sa.Column('note_verified_by_name', sa.String(length=100), nullable=True),
        sa.Column('note_verified_at', sa.DateTime(timezone=True), nullable=True),

        # Submission audit - who first reported the info
        sa.Column('submitted_by', sa.UUID(), nullable=True),
        sa.Column('submitted_by_name', sa.String(length=100), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        # Verification audit - who verified the building type
        sa.Column('verified_by', sa.UUID(), nullable = True),
        sa.Column('verified_by_name',sa.String(length=100), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),

        # Record audit - standard created_by + timestamps
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_by_name', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        ### Set Primary Key
        sa.PrimaryKeyConstraint('id'),

        ### Set Foreign Keys
        sa.ForeignKeyConstraint(['note_verified_by'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['submitted_by'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['verified_by'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['employees.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('company_id', 'block_key', 'building_type', name='uq_location_profiles_company_block_type'),
    )

    # Create Indexes
    op.create_index(
        op.f('ix_location_profiles_per_company'), 'location_profiles', ['company_id']
    )

    op.add_column('rts_reports',                 sa.Column('reviewed_by_name',     sa.String(100), nullable=True))
    op.add_column('incidents',                   sa.Column('driver_name',           sa.String(100), nullable=True))
    op.add_column('incidents',                   sa.Column('resolved_by_name',      sa.String(100), nullable=True))
    op.add_column('assignment_change_requests',  sa.Column('reviewed_by_name',      sa.String(100), nullable=True))
    op.add_column('anchor_points',               sa.Column('confirmed_by_name',     sa.String(100), nullable=True))
    op.add_column('package_manifests',           sa.Column('submitted_by_name',     sa.String(100), nullable=True))
    op.add_column('package_manifests',           sa.Column('acknowledged_by_name',  sa.String(100), nullable=True))
    op.add_column('dock_assignments',            sa.Column('assigned_by_name',      sa.String(100), nullable=True))
    op.add_column('location_difficulty_flags',   sa.Column('flagged_by_name',       sa.String(100), nullable=True))
    op.add_column('misrouted_package_flags',     sa.Column('resolved_by_name',      sa.String(100), nullable=True))
    op.add_column('schedule_change_requests',    sa.Column('reviewed_by_name',      sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('schedule_change_requests',   'reviewed_by_name')
    op.drop_column('misrouted_package_flags',     'resolved_by_name')
    op.drop_column('location_difficulty_flags',   'flagged_by_name')
    op.drop_column('dock_assignments',            'assigned_by_name')
    op.drop_column('package_manifests',           'acknowledged_by_name')
    op.drop_column('package_manifests',           'submitted_by_name')
    op.drop_column('anchor_points',               'confirmed_by_name')
    op.drop_column('assignment_change_requests',  'reviewed_by_name')
    op.drop_column('incidents',                   'resolved_by_name')
    op.drop_column('incidents',                   'driver_name')
    op.drop_column('rts_reports',                 'reviewed_by_name')
    op.drop_index(op.f('ix_location_profiles_per_company'), table_name='location_profiles')
    op.drop_table('location_profiles')