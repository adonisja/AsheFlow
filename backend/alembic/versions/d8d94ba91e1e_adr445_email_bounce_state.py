"""ADR-445: record that an address bounced.

Two nullable columns on `employees`. Nullable is the correct shape rather than a
default: NULL means "no bounce has been observed", which is a different and
weaker claim than "this address is known good". Every existing row is in that
state and backfilling a false would assert something we never checked.

`email_bounced_at` is indexed because the one query that matters is "show me the
employees in this company whose invite never landed" — a sparse predicate over a
mostly-NULL column, which is exactly what a partial index serves well.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: d8d94ba91e1e
Revises: 79d51e9b0610
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "d8d94ba91e1e"
down_revision = "79d51e9b0610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("email_bounced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        # 'Permanent' or 'Complaint' (ADR-445 D3). Transient bounces set
        # nothing -- a full mailbox is not a bad address, and flagging it would
        # train admins to ignore the flag.
        sa.Column("email_bounce_type", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_employees_email_bounced_at",
        "employees",
        ["email_bounced_at"],
        postgresql_where=sa.text("email_bounced_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_employees_email_bounced_at", table_name="employees")
    op.drop_column("employees", "email_bounce_type")
    op.drop_column("employees", "email_bounced_at")
