"""ADR-474 correction: `count` becomes a valid metric unit.

Real DA cards (2026-09-29) show Customer Delivery Feedback - Negative as a bare
COUNT, not a rate or a percentage. Without its own unit it would have to borrow
one, and borrowing `percent` would cap a count at 100 -- the same defect ADR-473
fixed on CDF.

Widens the CHECK only. No data moves: the unit list grows, and every existing
row keeps the unit it has.

Self-contained: no import from app.*.

Revision ID: 5b99f5189665
Revises: aeaead4ebc1e
Create Date: 2026-09-29
"""
from alembic import op

revision = "5b99f5189665"
down_revision = "aeaead4ebc1e"
branch_labels = None
depends_on = None

_CK = "ck_company_metric_targets_unit"
_OLD = "unit IN ('percent', 'dpmo', 'rate_per_100', 'score')"
_NEW = "unit IN ('percent', 'dpmo', 'rate_per_100', 'score', 'count')"


def upgrade() -> None:
    op.drop_constraint(_CK, "company_metric_targets", type_="check")
    op.create_check_constraint(_CK, "company_metric_targets", _NEW)


def downgrade() -> None:
    """Refuses if any row uses the unit being removed.

    Narrowing a CHECK under live rows is how a downgrade turns into a failed
    deploy halfway through. Better to say which rows block it.
    """
    import sqlalchemy as sa

    conn = op.get_bind()
    stuck = conn.execute(sa.text(
        "SELECT count(*) FROM company_metric_targets WHERE unit = 'count'"
    )).scalar() or 0
    if stuck:
        raise RuntimeError(
            f"{stuck} target(s) use unit 'count'. Re-unit or delete them before "
            "downgrading, or the narrowed CHECK cannot be applied."
        )
    op.drop_constraint(_CK, "company_metric_targets", type_="check")
    op.create_check_constraint(_CK, "company_metric_targets", _OLD)
