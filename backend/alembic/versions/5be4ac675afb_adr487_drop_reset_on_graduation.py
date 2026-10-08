"""ADR-487 D11c: drop employees.reset_on_graduation

The flag existed for ONE named simulation account. ADR-047 D2, which added it,
says so three times: "equally correct for simulation accounts", "simulation
accounts cycle through the full training system without polluting the walker
roster", and it names the account. It was never a product feature, which is why
its notification text read like a debug line — the message was honest about what
the code was for.

Graduation is now unconditional: pass the quiz, become a walker.

SUPERSEDES ADR-047 D2.

Revision ID: 5be4ac675afb
Revises: 1ff6e7990098
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = "5be4ac675afb"
down_revision = "1ff6e7990098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF EXISTS: a database that never ran b2c3d4e5f6a1 (a fresh one built from
    # a later baseline) has no column to drop, and an unconditional DROP would
    # abort the whole chain on it.
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS reset_on_graduation")


def downgrade() -> None:
    # Restored with the original default so a rollback leaves every existing row
    # on the non-reset path — which is the behaviour the column's removal makes
    # unconditional, so a downgrade changes nothing operationally.
    op.add_column(
        "employees",
        sa.Column("reset_on_graduation", sa.Boolean(), nullable=False,
                  server_default="false"),
    )
