"""ADR-473: scorecard targets become rows, not columns.

Ten `companies.scorecard_*_target` columns asserted a direction and a unit at
schema level. Checked against Amazon's own metric resource guides, FIVE asserted
them wrong: two defect rates modelled as percentages where higher passes, a
completion rate measuring something else entirely, a metric that is not scored at
all, and one folded inside another.

`meets_target` had no callers, so nothing was producing wrong verdicts -- this
is a correctness fix BEFORE the wiring.

THE FIVE MISMATCHED VALUES ARE CLEARED, NOT CONVERTED. A CDF of 84.9 entered as
"percentage, higher is better" is not a DPMO ceiling of anything. Carrying it
across would preserve the APPEARANCE of configuration while destroying its
meaning, which is worse than an empty field the Owner is asked to fill from their
own scorecard.

The five correct ones (pod, dsb_dpmo, fico, speeding_rate, signsignal_rate) ARE
carried across, with the shapes the guides confirm.

Reports what it moved and what it cleared: a silent data migration on a config
table is not something to discover later (ADR-468 precedent).

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: aeaead4ebc1e
Revises: a0ac4a1bc433
Create Date: 2026-09-28
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "aeaead4ebc1e"
down_revision = "a0ac4a1bc433"
branch_labels = None
depends_on = None

# column -> (metric_key, direction, unit). Shapes only; no thresholds (D5).
_CARRIED = {
    "scorecard_pod_target":              ("pod", "higher", "percent"),
    "scorecard_dsb_dpmo_target":         ("dsb_dpmo", "lower", "dpmo"),
    "scorecard_fico_target":             ("fico", "higher", "score"),
    "scorecard_speeding_rate_target":    ("speeding_rate", "lower", "rate_per_100"),
    "scorecard_signsignal_rate_target":  ("signsignal_rate", "lower", "rate_per_100"),
}

# Dropped without replacement values -- see the module docstring.
_CLEARED = [
    "scorecard_dcr_target",
    "scorecard_cdf_target",
    "scorecard_cc_target",
    "scorecard_dnr_dpmo_target",
    "scorecard_dvic_target",
]

_ALL = list(_CARRIED) + _CLEARED


def upgrade() -> None:
    op.create_table(
        "company_metric_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("metric_key", sa.String(length=50), nullable=False, index=True),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "metric_key",
                            name="uq_company_metric_targets_company_key"),
        sa.CheckConstraint("direction IN ('higher', 'lower')",
                           name="ck_company_metric_targets_direction"),
        sa.CheckConstraint("unit IN ('percent', 'dpmo', 'rate_per_100', 'score')",
                           name="ck_company_metric_targets_unit"),
        sa.CheckConstraint(
            "unit <> 'percent' OR (target_value >= 0 AND target_value <= 100)",
            name="ck_company_metric_targets_percent_range"),
        sa.CheckConstraint("target_value >= 0",
                           name="ck_company_metric_targets_non_negative"),
    )

    conn = op.get_bind()

    moved = 0
    for column, (key, direction, unit) in _CARRIED.items():
        rows = conn.execute(sa.text(
            f"SELECT id, {column} FROM companies WHERE {column} IS NOT NULL"
        )).fetchall()
        for company_id, value in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO company_metric_targets "
                    "(id, company_id, metric_key, target_value, direction, unit) "
                    "VALUES (:id, :cid, :k, :v, :d, :u)"
                ),
                {"id": str(uuid.uuid4()), "cid": str(company_id), "k": key,
                 "v": float(value), "d": direction, "u": unit},
            )
            moved += 1

    cleared = 0
    for column in _CLEARED:
        cleared += conn.execute(sa.text(
            f"SELECT count(*) FROM companies WHERE {column} IS NOT NULL"
        )).scalar() or 0

    for column in _ALL:
        op.drop_column("companies", column)

    print(f"ADR-473: carried {moved} target(s) across, "
          f"cleared {cleared} that did not match a real Amazon metric")


def downgrade() -> None:
    """Restores the columns and the five values that were carried across.

    LOSSY, and said plainly: the five cleared values are gone, because they were
    cleared rather than stored anywhere. That is the ambiguity this migration
    removed, so a downgrade cannot restore it -- and restoring a value entered
    against the wrong direction would be restoring a defect.
    """
    for column, (_key, _d, unit) in _CARRIED.items():
        kind = sa.Integer() if unit in ("score", "dpmo") else sa.Float()
        op.add_column("companies", sa.Column(column, kind, nullable=True))
    for column in _CLEARED:
        kind = sa.Integer() if "dpmo" in column else sa.Float()
        op.add_column("companies", sa.Column(column, kind, nullable=True))

    conn = op.get_bind()
    for column, (key, _d, _u) in _CARRIED.items():
        conn.execute(sa.text(
            f"UPDATE companies c SET {column} = t.target_value "
            "FROM company_metric_targets t "
            "WHERE t.company_id = c.id AND t.metric_key = :k"
        ), {"k": key})

    op.drop_table("company_metric_targets")
