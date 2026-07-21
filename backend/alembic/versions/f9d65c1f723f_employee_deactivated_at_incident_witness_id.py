"""employee deactivated_at + incident witness_id (ADR-221)

Revision ID: f9d65c1f723f
Revises: d9fa36bc25ab
Create Date: 2026-07-21

ADR-221: employees.deactivated_at (departure tombstone for the 6-month name-
redaction clock) + incidents.witness_id (maps the previously free-text
witness_name to an employee FK so it's redactable on departure).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f9d65c1f723f"
down_revision = "d9fa36bc25ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("witness_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "incidents_witness_id_fkey", "incidents", "employees",
        ["witness_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("incidents_witness_id_fkey", "incidents", type_="foreignkey")
    op.drop_column("incidents", "witness_id")
    op.drop_column("employees", "deactivated_at")
