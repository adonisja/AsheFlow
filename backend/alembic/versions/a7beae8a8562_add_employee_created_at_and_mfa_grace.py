"""Add employees.created_at and employees.mfa_grace_started_at (ADR-377 D2)

The MFA grace period needs a clock, and there was none: Employee had no
created_at at all. `invited_at` exists but is reset on re-invite, so a deadline
hung off it would move every time someone was re-invited.

Both columns are nullable, and NEITHER is backfilled.

created_at is NOT backfilled from invited_at. They are different facts:
invited_at is when an invite was issued, it is reset on re-invite, and an
employee created without an invite never has one. Copying it into created_at
would record a fabricated birthday that later reads cannot distinguish from a
real one. Existing rows keep NULL, which is the honest answer to "when was this
created?" for a row that predates the column.

mfa_grace_started_at is deliberately NOT backfilled. It is stamped on the first
sign-in after enforcement ships. Backfilling it to created_at would put every
existing employee instantly past a 14-day deadline (the staging accounts date
from 2026-05-07), which is a day-one mass lockout.

Revision ID: a7beae8a8562
Revises: 5600ba7f9958
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "a7beae8a8562"
down_revision = "5600ba7f9958"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "employees",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("mfa_grace_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_employees_created_at", "employees", ["created_at"], unique=False
    )

    # No backfill. invited_at is not a creation time (it is reset on re-invite,
    # and not every employee was invited), and now() would date a months-old row
    # to this deploy. Both are fabricated facts indistinguishable from real ones
    # on later reads. NULL means "created before this column existed", which is
    # true and checkable.


def downgrade():
    op.drop_index("ix_employees_created_at", table_name="employees")
    op.drop_column("employees", "mfa_grace_started_at")
    op.drop_column("employees", "created_at")
