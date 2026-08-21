"""ADR-263: role scoping for training curriculum (walker / driver tracks)

Adds a multi-valued `roles` column to training_curriculums so a driver
curriculum can coexist with the walker one without walker trainees receiving
driver vehicle-safety tasks.

Backfill: every existing row is walker material, so server_default="{walker}"
covers them. The shared items (ADP, Discord, attendance, NY lunch law) are then
widened to {walker,driver} by topic_title prefix so the driver seed does not
duplicate them.

Revision ID: 83e4cd66249c
Revises: a9f9098411e4
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "83e4cd66249c"
down_revision = "a9f9098411e4"
branch_labels = None
depends_on = None


# Shared curriculum items — policy that applies identically to both tracks.
# Matched by prefix because titles are long and carry parenthetical detail.
# Kept narrow deliberately: a false positive here silently hands a walker-only
# topic to drivers, which is the exact failure this ADR exists to prevent.
_SHARED_TITLE_PREFIXES = [
    "Discord:",
    "Amazon AZ:",
    "ADP:",
    "Contact: Dispatch for delivery/route issues",
    "Attendance policy:",
    "Bonus hours:",
    "NY State law:",
]


def upgrade() -> None:
    op.add_column(
        "training_curriculums",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(20)),
            nullable=False,
            server_default="{walker}",
        ),
    )

    # Widen shared policy items to both tracks.
    conn = op.get_bind()
    for prefix in _SHARED_TITLE_PREFIXES:
        conn.execute(
            sa.text(
                "UPDATE training_curriculums "
                "SET roles = ARRAY['walker','driver'] "
                "WHERE topic_title LIKE :pfx"
            ),
            {"pfx": f"{prefix}%"},
        )


def downgrade() -> None:
    op.drop_column("training_curriculums", "roles")
