"""ADR-410 — Truck.amazon_anchor_* as the BTR sheet identifier.

Amazon prints a static per-truck anchor point on every BTR sheet. It is the only
stable per-truck identifier there: the BTR label itself rotates between trucks.

Distinct from initial_anchor_*, which is OUR chosen territory seed read by
run_sort — see ADR-410 D2. Nothing in the sort reads these columns.

Revision ID: 5831fdbb4827
Revises: e52a0400d48b
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "5831fdbb4827"
down_revision = "e52a0400d48b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trucks", sa.Column("amazon_anchor_lat", sa.Float(), nullable=True))
    op.add_column("trucks", sa.Column("amazon_anchor_lng", sa.Float(), nullable=True))
    op.add_column(
        "trucks",
        sa.Column("amazon_anchor_set_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "trucks",
        sa.Column("amazon_anchor_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_trucks_amazon_anchor_set_by_employees",
        "trucks", "employees",
        ["amazon_anchor_set_by"], ["id"],
        ondelete="SET NULL",
    )
    # PARTIAL unique index: most trucks never register an anchor, so many NULL
    # rows must coexist. Uniqueness is what lets the resolver treat a match as
    # unambiguous (ADR-410 D3).
    op.create_index(
        "uq_trucks_company_amazon_anchor",
        "trucks",
        ["company_id", "amazon_anchor_lat", "amazon_anchor_lng"],
        unique=True,
        postgresql_where=sa.text("amazon_anchor_lat IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_trucks_company_amazon_anchor", table_name="trucks")
    op.drop_constraint("fk_trucks_amazon_anchor_set_by_employees", "trucks", type_="foreignkey")
    op.drop_column("trucks", "amazon_anchor_set_at")
    op.drop_column("trucks", "amazon_anchor_set_by")
    op.drop_column("trucks", "amazon_anchor_lng")
    op.drop_column("trucks", "amazon_anchor_lat")
