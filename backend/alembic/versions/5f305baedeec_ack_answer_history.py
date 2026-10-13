"""Acknowledgements keep every answer; one FINAL answer per notification (ADR-505).

ADR-494 made notification_id UNIQUE, so the first answer was the only one. A person
who tapped "Later" (skipped) and later confirmed stayed recorded as "skipped" --
reproduced on staging 2026-10-13. The guarantee worth keeping is "one FINAL answer",
which a partial unique index states exactly.

Index changes only, no data rewrite. Every existing row already satisfies "at most
one per notification", so it satisfies "at most one final".

Revision ID: 5f305baedeec
Revises: b771228f1f42
"""
from alembic import op
import sqlalchemy as sa

revision = "5f305baedeec"
down_revision = "b771228f1f42"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_ack_notification", "notification_acknowledgements", type_="unique")
    op.create_index(
        "ix_notification_acknowledgements_notification_id",
        "notification_acknowledgements", ["notification_id"],
    )
    op.create_index(
        "uq_ack_final_answer", "notification_acknowledgements", ["notification_id"],
        unique=True,
        postgresql_where=sa.text("action IN ('confirmed', 'unavailable')"),
    )


def downgrade():
    # Refuses if history exists (two rows for one notification): the old UNIQUE
    # cannot be restored over it without deleting evidence, which a downgrade
    # must not do silently.
    op.drop_index("uq_ack_final_answer", table_name="notification_acknowledgements")
    op.drop_index("ix_notification_acknowledgements_notification_id",
                  table_name="notification_acknowledgements")
    op.create_unique_constraint("uq_ack_notification", "notification_acknowledgements",
                                ["notification_id"])
