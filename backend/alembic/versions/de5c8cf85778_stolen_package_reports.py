"""stolen_package_reports: one theft, a DA version and a reviewer version (ADR-512).

Revision ID: de5c8cf85778
Revises: cd152324408d
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "de5c8cf85778"
down_revision = "cd152324408d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stolen_package_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(10), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("da_employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_date", sa.Date(), nullable=False),
        sa.Column("incident_time", sa.Time(), nullable=True),
        sa.Column("incident_address", sa.Text(), nullable=True),
        sa.Column("anchor_point_address", sa.String(255), nullable=True),
        sa.Column("lmet_called", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lmet_case_number", sa.String(64), nullable=True),
        sa.Column("bike_locks_used", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cart_cover_used", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("totes_stolen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cart_stolen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("packages_stolen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tbas", postgresql.ARRAY(sa.String(40)), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reviewer_comments", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pi_cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version IN ('da', 'reviewer')", name="ck_stolen_report_version"),
        sa.CheckConstraint("totes_stolen >= 0 AND packages_stolen >= 0", name="ck_stolen_report_counts"),
    )
    op.create_index("ix_stolen_package_reports_company_id", "stolen_package_reports", ["company_id"])
    op.create_index("ix_stolen_package_reports_incident_id", "stolen_package_reports", ["incident_id"])
    op.create_index("ix_stolen_package_reports_author_id", "stolen_package_reports", ["author_id"])
    op.create_index("uq_stolen_report_version", "stolen_package_reports", ["incident_id", "version"], unique=True)


def downgrade():
    op.drop_table("stolen_package_reports")
