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

    # Backfill with the fold as it stood AT THIS REVISION, inlined rather than
    # imported.
    #
    # `from app.services.door_key import door_key` would run today's fold, not
    # this revision's: an edit to the rule would silently change what this
    # backfill produces, and a rename would crash a fresh
    # `alembic upgrade head` outright (see 46f04059c09f, which did exactly
    # that). A migration must express the schema at its own point in history,
    # so the only safe dependency is the standard library.
    #
    # Python rather than SQL because the fold is ORDERED — ordinals before
    # directions — and nested REPLACEs would be a second implementation of the
    # rule. Volume is small; this is a research table.
    import re as _re

    _PUNCT      = _re.compile(r"[.,#]")
    _ORDINAL    = _re.compile(r"\b(\d+)(st|nd|rd|th)\b")
    _DIRECTION  = _re.compile(r"\b(north|south|east|west)\b")
    _UNIT_TAIL  = _re.compile(r"\b(apartment|apt|unit|suite|ste)\b.*$")
    _WHITESPACE = _re.compile(r"\s+")
    _STREET_TYPES = [
        (_re.compile(r"\b(street|st)\b"), "st"),
        (_re.compile(r"\b(avenue|ave|av)\b"), "ave"),
        (_re.compile(r"\b(boulevard|blvd)\b"), "blvd"),
        (_re.compile(r"\b(road|rd)\b"), "rd"),
        (_re.compile(r"\b(place|pl)\b"), "pl"),
        (_re.compile(r"\b(drive|dr)\b"), "dr"),
        (_re.compile(r"\b(lane|ln)\b"), "ln"),
        (_re.compile(r"\b(parkway|pkwy)\b"), "pkwy"),
    ]

    def door_key(address: str) -> str:
        s = address.lower()
        s = _PUNCT.sub(" ", s)
        s = _ORDINAL.sub(r"\1", s)
        s = _DIRECTION.sub(lambda m: m.group(0)[0], s)
        for pattern, canon in _STREET_TYPES:
            s = pattern.sub(canon, s)
        s = _UNIT_TAIL.sub("", s)
        return _WHITESPACE.sub(" ", s).strip()

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
