"""Add company_id to all tenant-scoped tables and backfill seed company

Revision ID: h2b3c4d5e6f7
Revises: h1a2b3c4d5e6
Create Date: 2026-05-07

Strategy:
  1. Add company_id as nullable UUID to every table (no FK yet).
  2. Backfill all existing rows with the seed company ID.
  3. Add NOT NULL constraint to all tables except audit_logs
     (audit_logs keeps nullable to support super_admin cross-company actions).
  4. Add FK constraints and indexes.

Seed company ID: a0000000-0000-0000-0000-000000000001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h2b3c4d5e6f7'
down_revision = 'h1a2b3c4d5e6'
branch_labels = None
depends_on = None

SEED_COMPANY_ID = 'a0000000-0000-0000-0000-000000000001'

# Tables that get company_id NOT NULL + FK
TENANT_TABLES = [
    'employees',
    'trucks',
    'truck_assignments',
    'assignment_members',
    'employee_off_days',
    'employee_relationships',
    'time_off_requests',
    'dispatch_confirmations',
    'training_curriculums',
    'training_records',
    'training_tasks',
    'trainer_continuation_requests',
    'trainer_coverage',
    'trainer_marks',
    'notifications',
    'check_ins',
    'departures',
    'walker_ratings',
    'fuel_mileage_logs',
    'vehicle_inspections',
    'feedbacks',
    'assignment_change_requests',
    'schedule_change_requests',
    'incidents',
    'dock_assignments',
    'station_arrivals',
    'package_manifests',
    'crew_compliance',
    'driver_check_ins',
    'rts_reports',
    'station_handoffs',
    'anchor_points',
]

# audit_logs gets company_id nullable, no FK — supports super_admin cross-company actions
AUDIT_TABLES = ['audit_logs']


def upgrade() -> None:
    # ── Step 1: add nullable company_id to all tables ─────────────────────────
    for table in TENANT_TABLES + AUDIT_TABLES:
        op.add_column(table, sa.Column(
            'company_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ))

    # ── Step 2: backfill all existing rows with seed company ──────────────────
    for table in TENANT_TABLES + AUDIT_TABLES:
        op.execute(
            f"UPDATE {table} SET company_id = '{SEED_COMPANY_ID}' WHERE company_id IS NULL"
        )

    # ── Step 3: set NOT NULL on tenant tables ─────────────────────────────────
    for table in TENANT_TABLES:
        op.alter_column(table, 'company_id', nullable=False)
    # audit_logs stays nullable intentionally

    # ── Step 4: add indexes ───────────────────────────────────────────────────
    for table in TENANT_TABLES + AUDIT_TABLES:
        op.create_index(
            f'ix_{table}_company_id',
            table, ['company_id'],
            unique=False,
        )

    # ── Step 5: add FK constraints on tenant tables ───────────────────────────
    for table in TENANT_TABLES:
        op.create_foreign_key(
            f'fk_{table}_company_id',
            table, 'companies',
            ['company_id'], ['id'],
            ondelete='RESTRICT',
        )
    # audit_logs: no FK — intentionally loose reference


def downgrade() -> None:
    # Drop FKs first, then indexes, then columns
    for table in TENANT_TABLES:
        op.drop_constraint(f'fk_{table}_company_id', table, type_='foreignkey')

    for table in TENANT_TABLES + AUDIT_TABLES:
        op.drop_index(f'ix_{table}_company_id', table_name=table)
        op.drop_column(table, 'company_id')
