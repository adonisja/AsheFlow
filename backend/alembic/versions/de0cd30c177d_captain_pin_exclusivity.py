"""ADR-256 D17a: a pin is exclusive in both directions

`uq_captain_truck_familiarity (employee_id, truck_id)` only stops ONE captain being
pinned twice to the SAME truck. It does not stop two different captains being pinned
to one truck — and that happens across days without anyone doing anything wrong:

    Mon: pin A to Viking          -> row (A, Viking, pinned)
    Tue: A is off, pin B to Viking -> row (B, Viking, pinned)   <- accepted today
    Wed: both available           -> assign_captains places whichever it reaches
                                     first; the other pin is silently ignored

Two partial unique indexes close it:
  uq_captain_pin_one_per_truck    — one pinned captain per truck
  uq_captain_pin_one_per_captain  — one pin per captain, total

Existing pins are de-duplicated before the indexes are created, otherwise CREATE
UNIQUE INDEX fails on data that predates the rule. The survivor is the most recently
held row (last_held_at, then created_at) — the pin the operator most likely still
means. Losers are unpinned, not deleted: the familiarity counters they carry are
real history.

Revision ID: de0cd30c177d
Revises: 15f20fe600ae
Create Date: 2026-08-08
"""
from alembic import op

revision = "de0cd30c177d"
down_revision = "15f20fe600ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── De-duplicate before constraining ──────────────────────────────────────
    # Keep one pin per truck: newest by last_held_at, then created_at.
    op.execute("""
        UPDATE captain_truck_familiarity SET pinned = false
        WHERE pinned = true AND id NOT IN (
            SELECT DISTINCT ON (truck_id) id
            FROM captain_truck_familiarity
            WHERE pinned = true
            ORDER BY truck_id, last_held_at DESC NULLS LAST, created_at DESC
        )
    """)
    # Then one pin per captain, same rule. Runs second so a captain who survived the
    # first pass on two trucks is narrowed to one.
    op.execute("""
        UPDATE captain_truck_familiarity SET pinned = false
        WHERE pinned = true AND id NOT IN (
            SELECT DISTINCT ON (employee_id) id
            FROM captain_truck_familiarity
            WHERE pinned = true
            ORDER BY employee_id, last_held_at DESC NULLS LAST, created_at DESC
        )
    """)

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_captain_pin_one_per_truck "
        "ON captain_truck_familiarity (truck_id) WHERE pinned = true"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_captain_pin_one_per_captain "
        "ON captain_truck_familiarity (employee_id) WHERE pinned = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_captain_pin_one_per_captain")
    op.execute("DROP INDEX IF EXISTS uq_captain_pin_one_per_truck")
