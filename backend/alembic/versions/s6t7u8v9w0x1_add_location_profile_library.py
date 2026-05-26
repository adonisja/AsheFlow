"""add location_profile_library table and nomination_status to location_profiles

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from typing import Sequence, Union

revision: str = 's6t7u8v9w0x1'
down_revision: Union[str, Sequence[str], None] = 'r5s6t7u8v9w0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "location_profile_library",

        # Identity
        sa.Column('id',            sa.UUID(), nullable=False),
        sa.Column('block_key',     sa.String(length=60),  nullable=False),
        sa.Column('building_type', sa.String(length=30),  nullable=False),
        sa.Column('workload_class',sa.String(length=20),  nullable=False),

        # Library lifecycle
        sa.Column('library_status',          sa.String(length=20), server_default='active',  nullable=False),
        sa.Column('agreement_source_count',  sa.Integer(),          server_default='0',       nullable=False),
        sa.Column('last_conflict_at',        sa.DateTime(timezone=True), nullable=True),

        # Notes
        sa.Column('operational_note',     sa.Text(),    nullable=True),
        sa.Column('note_verified',        sa.Boolean(), server_default='false', nullable=False),
        sa.Column('note_verified_by',     sa.UUID(),    nullable=True),
        sa.Column('note_verified_by_name',sa.String(length=100), nullable=True),
        sa.Column('note_verified_at',     sa.DateTime(timezone=True), nullable=True),

        # Promotion audit
        sa.Column('promoted_from_company_ids', ARRAY(sa.UUID()), nullable=True),
        sa.Column('promoted_at',               sa.DateTime(timezone=True), nullable=True),
        sa.Column('promoted_by',               sa.UUID(), nullable=True),
        sa.Column('promoted_by_name',          sa.String(length=100), nullable=True),

        # Record audit
        sa.Column('created_by',      sa.UUID(), nullable=True),
        sa.Column('created_by_name', sa.String(length=100), nullable=True),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by',      sa.UUID(), nullable=True),
        sa.Column('updated_by_name', sa.String(length=100), nullable=True),
        sa.Column('updated_at',      sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('block_key', 'building_type', name='uq_location_profile_library_block_type'),

        # Valid library lifecycle states — enforced at DB level
        sa.CheckConstraint(
            "library_status IN ('active', 'conflict_pending', 'deprecated')",
            name='ck_location_profile_library_library_status'
        ),

        # Valid building types — matches the taxonomy in ADR-093
        sa.CheckConstraint(
            "building_type IN ('mailroom', 'receptionist', 'walkup', 'elevator', 'biz_front', 'biz_freight', 'biz_security', 'biz_loading_dock')",
            name='ck_location_profile_library_building_type'
        ),

        # Valid workload classes — derived from building_type, stored for fast queries
        sa.CheckConstraint(
            "workload_class IN ('bulk_drop', 'standard', 'high_touch', 'high_wait')",
            name='ck_location_profile_library_workload_class'
        ),
    )

    op.create_index('ix_location_profile_library_block_key', 'location_profile_library', ['block_key'])

    # Add nomination_status to location_profiles — tracks promotion pipeline per company record
    # null = not in pipeline | nominated = queued for super admin | promoted = in library | rejected = declined
    op.add_column(
        'location_profiles',
        sa.Column('nomination_status', sa.String(length=20), nullable=True)
    )

    # Check constraints on location_profiles — these were missing from the prior migration (r5s6t7u8v9w0)
    # Adding them here since we are already touching this table with nomination_status
    op.create_check_constraint(
        'ck_location_profiles_building_type_status',
        'location_profiles',
        "building_type_status IN ('pending', 'verified', 'locked')"
    )
    op.create_check_constraint(
        'ck_location_profiles_nomination_status',
        'location_profiles',
        "nomination_status IN ('nominated', 'promoted', 'rejected')"
    )
    op.create_check_constraint(
        'ck_location_profiles_building_type',
        'location_profiles',
        "building_type IN ('mailroom', 'receptionist', 'walkup', 'elevator', 'biz_front', 'biz_freight', 'biz_security', 'biz_loading_dock')"
    )
    op.create_check_constraint(
        'ck_location_profiles_workload_class',
        'location_profiles',
        "workload_class IN ('bulk_drop', 'standard', 'high_touch', 'high_wait')"
    )


def downgrade() -> None:
    # Drop location_profiles check constraints added in this migration
    op.drop_constraint('ck_location_profiles_workload_class',       'location_profiles', type_='check')
    op.drop_constraint('ck_location_profiles_building_type',        'location_profiles', type_='check')
    op.drop_constraint('ck_location_profiles_nomination_status',    'location_profiles', type_='check')
    op.drop_constraint('ck_location_profiles_building_type_status', 'location_profiles', type_='check')
    op.drop_column('location_profiles', 'nomination_status')

    op.drop_index('ix_location_profile_library_block_key', table_name='location_profile_library')
    op.drop_table('location_profile_library')
