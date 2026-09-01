"""ADR-291 D11 — routes.flex_package_count: the count read off Amazon Flex

Revision ID: 425f1740dcf3
Revises: a79aad3693fb
Create Date: 2026-08-24

Three additive nullable columns.

WHY package_count IS NOT ENOUGH. route_sort derives it as
sum(len(t.packages)) — and in workforce mode a "package" is one captain-entered
ADDRESS, not a parcel. A route carrying one tote with three addresses reports 3
while that tote physically holds fifty. `dashboard_summaries` and
`assignment_history` both read package_count, so leaving it alone understates
real throughput by an order of magnitude in every report.

Amazon Flex shows a real count while the walker scans the route's totes, so the
captain records it there. Granularity lost: per-tote counts. Retained: tote
count, OV count, OV size, and a true per-route package total.

NULLABLE, and it must stay so. NULL means "not recorded yet"; 0 means the route
genuinely carried nothing. A NOT NULL default of 0 would make those
indistinguishable, which is exactly the zero-versus-absence failure ADR-294
exists to prevent and that this codebase already paid for on 2026-07-29.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "425f1740dcf3"
down_revision = "a79aad3693fb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("routes", sa.Column("flex_package_count", sa.Integer(), nullable=True))
    op.add_column(
        "routes",
        sa.Column("flex_count_recorded_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "routes",
        sa.Column("flex_count_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_routes_flex_count_recorded_by", "routes", "employees",
        ["flex_count_recorded_by"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_routes_flex_count_recorded_by", "routes", type_="foreignkey")
    op.drop_column("routes", "flex_count_recorded_at")
    op.drop_column("routes", "flex_count_recorded_by")
    op.drop_column("routes", "flex_package_count")
