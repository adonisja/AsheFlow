"""ADR-312 — remove superseded company_zone revisions

Revision ID: e506600c0541
Revises: 683ef38406fa
Create Date: 2026-08-26

The four zone upserts deactivated the previous row and inserted a new one,
deleting nothing, so `company_zones` grew by one dead row per edit forever.

Every reader in the codebase filters `is_active = true` (sort.py x5,
run_sort.py:212, package_intake.py:98), so an inactive row is never read by
anything. The edit history they might have preserved is already recorded — and
better — by the `company_zone.upserted` audit entries, which carry the actor and
timestamp that CompanyZone does not.

The endpoints now DELETE the superseded revision (ADR-312 D6). This clears the
rows the old behaviour left behind.

Irreversible by design: the downgrade cannot resurrect deleted rows, and
recreating them as inactive would restore the garbage this removes.
"""
from alembic import op
import sqlalchemy as sa

revision = "e506600c0541"
down_revision = "683ef38406fa"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Count first so the log says what was removed, and so a surprising number
    # is visible rather than silent.
    before = conn.execute(sa.text(
        "SELECT count(*) FROM company_zones WHERE is_active = false"
    )).scalar()

    # Guard: never touch a live zone. The WHERE clause already excludes them;
    # this asserts the invariant the deletion depends on rather than trusting it.
    live_before = conn.execute(sa.text(
        "SELECT count(*) FROM company_zones WHERE is_active = true"
    )).scalar()

    conn.execute(sa.text("DELETE FROM company_zones WHERE is_active = false"))

    live_after = conn.execute(sa.text(
        "SELECT count(*) FROM company_zones WHERE is_active = true"
    )).scalar()
    assert live_after == live_before, (
        f"ADR-312 migration removed a LIVE zone: {live_before} -> {live_after}"
    )
    print(f"ADR-312: removed {before} superseded company_zone row(s); "
          f"{live_after} active zone(s) untouched")


def downgrade():
    # Deliberately a no-op. The deleted rows were unreachable by every reader
    # and duplicated the audit trail; recreating them would restore garbage.
    pass
