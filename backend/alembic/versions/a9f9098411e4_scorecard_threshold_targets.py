"""ADR-262: per-DSP Amazon scorecard tier targets on company_configs

Ten nullable columns. Additive, no backfill: NULL means "no target configured",
which callers must render as "no judgement", never as a failure.

Revision ID: a9f9098411e4
Revises: 07bc69de93ca
Create Date: 2026-08-07

Re-parented 2026-08-07 from d5469c0fe260 to 07bc69de93ca (ADR-256 captain /
field_supervisor / driver_trainee roles), which committed first and took the
same parent. Both claiming d5469c0fe260 would leave two heads and fail the next
deploy with a multi-head overlap. No DDL change — purely a chain fix.
"""
from alembic import op
import sqlalchemy as sa

revision = "a9f9098411e4"
down_revision = "07bc69de93ca"
branch_labels = None
depends_on = None


# (column, type) — direction is NOT stored; it is domain truth in
# services/company_config.py::METRIC_DIRECTION (ADR-262).
_COLUMNS = [
    ("scorecard_dcr_target",              sa.Float()),
    ("scorecard_dnr_dpmo_target",         sa.Integer()),
    ("scorecard_pod_target",              sa.Float()),
    ("scorecard_cc_target",               sa.Float()),
    ("scorecard_cdf_target",              sa.Float()),
    ("scorecard_dsb_dpmo_target",         sa.Integer()),
    ("scorecard_fico_target",             sa.Integer()),
    ("scorecard_speeding_rate_target",    sa.Float()),
    ("scorecard_signsignal_rate_target",  sa.Float()),
    ("scorecard_dvic_target",             sa.Float()),
]


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("company_configs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("company_configs", name)
