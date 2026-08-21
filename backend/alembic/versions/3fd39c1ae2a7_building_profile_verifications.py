"""building_profile_verifications — one row per verifier (ADR-276 D3)

Revision ID: 3fd39c1ae2a7
Revises: ba220f74f61d
Create Date: 2026-08-19

The unique constraint on (profile_id, employee_id) is the point: it stops one
person reaching the agreement threshold alone by verifying twice. Enforced in
the database rather than the handler because that is where a future code path
cannot forget it.

No backfill (ADR-276, Open). Legacy profiles keep their agreement_count and
start with zero verification rows: synthesising a row from `verified_by` would
invent a verifier identity for every confirmation but the last, since that
column was overwritten each time. A legacy profile sitting at 1 needs one fresh
confirmation under the new rules, which is honest about what is actually known.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3fd39c1ae2a7"
down_revision = "ba220f74f61d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "building_profile_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("employee_name", sa.String(length=100), nullable=True),
        sa.Column("employee_role", sa.String(length=30), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("building_type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["building_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("profile_id", "employee_id",
                            name="uq_building_profile_verification_once"),
    )
    op.create_index("ix_bpv_company_id", "building_profile_verifications", ["company_id"])
    op.create_index("ix_bpv_profile_id", "building_profile_verifications", ["profile_id"])
    op.create_index("ix_bpv_employee_id", "building_profile_verifications", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_bpv_employee_id", table_name="building_profile_verifications")
    op.drop_index("ix_bpv_profile_id", table_name="building_profile_verifications")
    op.drop_index("ix_bpv_company_id", table_name="building_profile_verifications")
    op.drop_table("building_profile_verifications")
