"""ADR-451: one bootstrap admin, and an email change verified before it lands.

Three columns on `employees`:

  is_bootstrap_admin       the provisioning row that opens a tenant. The
                           endpoint matches on THIS, not on email -- "does this
                           company already have a bootstrap admin?" must not
                           depend on what the caller typed.
  pending_email            a requested address, NOT yet in effect. The live
                           `email` is untouched until the new one is proven,
                           so a typo cannot lock an admin out of a live tenant.
  pending_email_expires_at 3 days. On expiry the pending value is cleared and
                           `email` was never written -- that IS the revert.

NOTHING IS BACKFILLED, deliberately. Inferring "the oldest admin per company"
is a guess, and it is wrong exactly when the original admin was offboarded and
replaced: it would mark someone who never held the role, and ADR-451 D3 then
locks their name against correction. A company predating this ADR reports "no
bootstrap admin" and offers to create one, which is the truth.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: f501ec69b808
Revises: d8d94ba91e1e
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "f501ec69b808"
down_revision = "d8d94ba91e1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("is_bootstrap_admin", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column("employees", sa.Column("pending_email", sa.String(length=255), nullable=True))
    op.add_column(
        "employees",
        sa.Column("pending_email_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Partial: at most one row per company carries the flag, so the index stays
    # tiny while answering the only question asked of it -- "who is this
    # company's bootstrap admin?"
    op.create_index(
        "ix_employees_bootstrap_admin",
        "employees",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_bootstrap_admin"),
    )
    # The expiry job scans for due rows; sparse, so partial again.
    op.create_index(
        "ix_employees_pending_email_expires",
        "employees",
        ["pending_email_expires_at"],
        postgresql_where=sa.text("pending_email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_employees_pending_email_expires", table_name="employees")
    op.drop_index("ix_employees_bootstrap_admin", table_name="employees")
    op.drop_column("employees", "pending_email_expires_at")
    op.drop_column("employees", "pending_email")
    op.drop_column("employees", "is_bootstrap_admin")
