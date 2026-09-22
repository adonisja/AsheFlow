"""ADR-452: the Owner is a role, not a provisioning artefact.

Renames `is_bootstrap_admin` -> `is_owner`, and the indexes with it.

A RENAME, not a new column. Two columns meaning the same thing is how they
drift: one gets written by a path somebody forgot to update, and the answer to
"who owns this company?" becomes a question about which column you read.

ALTER ... RENAME preserves the data, so the flag set by ADR-451 survives -- and
because ADR-451 deliberately backfilled nothing, there is nothing here to guess
at either.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: db8751d428ad
Revises: f501ec69b808
Create Date: 2026-09-22
"""
from alembic import op

revision = "db8751d428ad"
down_revision = "f501ec69b808"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("employees", "is_bootstrap_admin", new_column_name="is_owner")
    # The partial index's WHERE clause names the old column, so it has to be
    # rebuilt rather than renamed -- a renamed index would still reference
    # `is_bootstrap_admin` and fail on the next write.
    op.drop_index("ix_employees_bootstrap_admin", table_name="employees")
    op.execute(
        "CREATE UNIQUE INDEX ix_employees_owner ON employees (company_id) "
        "WHERE is_owner"
    )


def downgrade() -> None:
    op.drop_index("ix_employees_owner", table_name="employees")
    op.alter_column("employees", "is_owner", new_column_name="is_bootstrap_admin")
    op.execute(
        "CREATE UNIQUE INDEX ix_employees_bootstrap_admin ON employees (company_id) "
        "WHERE is_bootstrap_admin"
    )
