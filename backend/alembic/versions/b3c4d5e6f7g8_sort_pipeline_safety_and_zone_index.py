"""sort pipeline: partial unique index on active truck zones, zone_date index

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-29

Two changes:

1. Partial unique index on truck_zones(company_id, truck_id, zone_date)
   WHERE is_active = true.

   Prevents concurrent POST /sort/run calls for the same company+date from
   producing duplicate active zones. The deactivate-then-insert pattern in
   persist_zones is idempotent for sequential calls, but two concurrent
   requests would both read is_active=True zones, both deactivate them, and
   both insert — leaving double the rows active. This index makes the second
   insert fail with an IntegrityError instead.

   Note: a truck can have multiple active zones on the same date (overflow
   clusters). The index is per (company_id, truck_id, zone_date) which would
   prevent that. Since overflow is a real scenario, we use a UNIQUE index only
   on (company_id, zone_date) scoped to non-overflow zones instead — i.e.,
   we leave this as a partial index that allows multiple rows per truck but
   at least prevents fully duplicate (company_id, zone_date) runs from both
   committing at the same time. The real fix for concurrent runs is an
   application-level lock (Redis SETNX), but the index gives DB-level safety.

   Revised: unique on (company_id, zone_label, zone_date) WHERE is_active — zone
   labels are unique per run (truck name + overflow/seq suffix), so a duplicate
   run producing identical labels would be caught.

2. Index on truck_zones(zone_date) already exists (from v9w0x1y2z3a4 migration).
   No duplicate needed.
"""

from alembic import op


revision = 'b3c4d5e6f7g8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial unique index: same (company, label, date) cannot be active twice.
    # A concurrent re-sort producing the same zone labels is caught at DB level.
    op.execute("""
        CREATE UNIQUE INDEX uq_truck_zones_active_label
        ON truck_zones (company_id, zone_label, zone_date)
        WHERE is_active = true
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_truck_zones_active_label")
