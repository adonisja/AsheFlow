"""ADR-417 D7: door_key on collected_address_profiles

Adds the folded comparison key used by the campaign-wide duplicate check, and
backfills it for existing rows using the same fold the application uses.

Revision ID: c1e6dd96bf3a
Revises: 0e5917d6e99f
"""
from alembic import op
import sqlalchemy as sa

revision = "c1e6dd96bf3a"
down_revision = "0e5917d6e99f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collected_address_profiles",
        sa.Column("door_key", sa.String(length=200),
                  nullable=False, server_default=""),
    )
    op.create_index(
        "ix_collected_profiles_token_door",
        "collected_address_profiles",
        ["token_id", "door_key"],
    )

    # Backfill with the SAME fold as app.services.door_key, in Python rather
    # than SQL: the fold is ordered (ordinals before directions) and expressing
    # that as nested REPLACEs would be a second implementation of the rule that
    # could drift from the first. Existing volume is small — this is a research
    # table — so a row-by-row pass is the honest choice.
    from app.services.door_key import door_key

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, address FROM collected_address_profiles")
    ).fetchall()
    for row_id, address in rows:
        conn.execute(
            sa.text(
                "UPDATE collected_address_profiles "
                "SET door_key = :k WHERE id = :i"
            ),
            {"k": door_key(address or "")[:200], "i": row_id},
        )


def downgrade() -> None:
    op.drop_index("ix_collected_profiles_token_door",
                  table_name="collected_address_profiles")
    op.drop_column("collected_address_profiles", "door_key")
