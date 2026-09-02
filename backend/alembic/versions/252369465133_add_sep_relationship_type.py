"""Add 'sep' relationship type for dispatch separations (ADR-361)

A separation is a dispatcher's decision to keep two people apart. It has the
same dispatch effect as a ban but is authored by dispatch rather than by either
employee, so it appears in neither party's list.

Revision ID: 252369465133
Revises: 34d7780d715d
Create Date: 2026-09-02
"""
from alembic import op

revision = "252369465133"
down_revision = "34d7780d715d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The CHECK is the only thing gating the new value; the column is already
    # String(10) and 'sep' fits.
    op.drop_constraint(
        "ck_employee_relationships_type", "employee_relationships", type_="check"
    )
    op.create_check_constraint(
        "ck_employee_relationships_type",
        "employee_relationships",
        "relationship_type IN ('ban', 'fav', 'sep')",
    )


def downgrade() -> None:
    # Separations must go before the constraint narrows, or the CHECK cannot be
    # applied to existing rows.
    op.execute("DELETE FROM employee_relationships WHERE relationship_type = 'sep'")
    op.drop_constraint(
        "ck_employee_relationships_type", "employee_relationships", type_="check"
    )
    op.create_check_constraint(
        "ck_employee_relationships_type",
        "employee_relationships",
        "relationship_type IN ('ban', 'fav')",
    )
