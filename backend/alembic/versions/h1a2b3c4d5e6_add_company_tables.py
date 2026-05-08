"""Add companies, company_configs, and company_zones tables

Revision ID: h1a2b3c4d5e6
Revises: g1b2c3d4e5f6
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h1a2b3c4d5e6'
down_revision = 'g1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── companies ─────────────────────────────────────────────────────────────
    op.create_table(
        'companies',
        sa.Column('id',              postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',            sa.String(255),  nullable=False),
        sa.Column('slug',            sa.String(100),  nullable=False),
        sa.Column('amazon_dsp_code', sa.String(20),   nullable=True),
        sa.Column('timezone',        sa.String(64),   nullable=False, server_default='America/New_York'),
        sa.Column('is_active',       sa.Boolean(),    nullable=False, server_default='true'),
        sa.Column('created_at',      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_companies_slug',      'companies', ['slug'],      unique=True)
    op.create_index('ix_companies_is_active', 'companies', ['is_active'], unique=False)

    # ── company_configs ───────────────────────────────────────────────────────
    op.create_table(
        'company_configs',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),

        # Shift timing
        sa.Column('shift_start',   sa.Time(), nullable=True),
        sa.Column('shift_end',     sa.Time(), nullable=True),
        sa.Column('checkin_open',  sa.Time(), nullable=True),
        sa.Column('checkin_close', sa.Time(), nullable=True),

        # Operations
        sa.Column('rating_window_hours', sa.Integer(), nullable=True),
        sa.Column('invite_expiry_days',  sa.Integer(), nullable=True),

        # Crew requirements
        sa.Column('min_trainers_per_truck', sa.Integer(), nullable=True),
        sa.Column('min_walkers_per_truck',  sa.Integer(), nullable=True),

        # Training rules
        sa.Column('graduation_assignments',           sa.Integer(), nullable=True),
        sa.Column('debt_escalation_threshold',        sa.Integer(), nullable=True),
        sa.Column('phase4_pass_score',                sa.Float(),   nullable=True),
        sa.Column('underperforming_trainer_threshold', sa.Integer(), nullable=True),
        sa.Column('max_training_phase',               sa.Integer(), nullable=True),

        # Dispatch algorithm weights
        sa.Column('dispatch_weight_driver',        sa.Float(), nullable=True),
        sa.Column('dispatch_weight_trainer',       sa.Float(), nullable=True),
        sa.Column('dispatch_weight_walker',        sa.Float(), nullable=True),
        sa.Column('dispatch_mutual_bonus',         sa.Float(), nullable=True),
        sa.Column('dispatch_tridirectional_bonus', sa.Float(), nullable=True),
        sa.Column('dispatch_consecutive_penalty',  sa.Float(), nullable=True),
        sa.Column('dispatch_weight_cap',           sa.Float(), nullable=True),

        # Anomaly detection
        sa.Column('flag_threshold', sa.Float(), nullable=True),

        # Check-ins
        sa.Column('driver_checkin_count', sa.Integer(), nullable=True),
    )
    op.create_index('ix_company_configs_company_id', 'company_configs', ['company_id'], unique=True)
    op.create_foreign_key(
        'fk_company_configs_company_id',
        'company_configs', 'companies',
        ['company_id'], ['id'],
        ondelete='CASCADE',
    )

    # ── company_zones ─────────────────────────────────────────────────────────
    op.create_table(
        'company_zones',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id',     postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('parent_zone_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name',           sa.String(255), nullable=False),
        sa.Column('bounds',         postgresql.JSONB(),            nullable=True),
        sa.Column('is_active',      sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('created_at',     sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_company_zones_company_id',     'company_zones', ['company_id'],     unique=False)
    op.create_index('ix_company_zones_parent_zone_id', 'company_zones', ['parent_zone_id'], unique=False)
    op.create_foreign_key(
        'fk_company_zones_company_id',
        'company_zones', 'companies',
        ['company_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_company_zones_parent_zone_id',
        'company_zones', 'company_zones',
        ['parent_zone_id'], ['id'],
        ondelete='SET NULL',
    )

    # ── seed: DSP test company + config ───────────────────────────────────────
    # Values sourced from docs/SEED_COMPANY_CONFIG.md — the live hardcoded
    # defaults from the single-tenant version of AsheFlow.
    op.execute("""
        INSERT INTO companies (id, name, slug, amazon_dsp_code, timezone, is_active, created_at)
        VALUES (
            'a0000000-0000-0000-0000-000000000001',
            'DSP Test Company',
            'dsp-test',
            NULL,
            'America/New_York',
            true,
            now()
        );
    """)
    op.execute("""
        INSERT INTO company_configs (
            id, company_id,
            rating_window_hours, invite_expiry_days,
            min_trainers_per_truck, min_walkers_per_truck,
            graduation_assignments, debt_escalation_threshold,
            phase4_pass_score, underperforming_trainer_threshold, max_training_phase,
            dispatch_weight_driver, dispatch_weight_trainer, dispatch_weight_walker,
            dispatch_mutual_bonus, dispatch_tridirectional_bonus,
            dispatch_consecutive_penalty, dispatch_weight_cap,
            flag_threshold, driver_checkin_count
        ) VALUES (
            'b0000000-0000-0000-0000-000000000001',
            'a0000000-0000-0000-0000-000000000001',
            6, 7,
            2, 3,
            5, 3,
            90.0, 3, 4,
            0.70, 0.50, 0.30,
            0.10, 0.20,
            0.05, 0.85,
            1.0, 4
        );
    """)


def downgrade() -> None:
    op.drop_table('company_zones')
    op.drop_table('company_configs')
    op.drop_table('companies')
