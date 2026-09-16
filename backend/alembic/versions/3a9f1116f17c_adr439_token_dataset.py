"""ADR-439: a collection link is issued for one study.

ADR-421 separated the two collection PAGES. It did not separate the CREDENTIAL:
`_resolve_token` checked only that a token existed and was live, so one link was
valid on all four public endpoints — including `/submit-day`, which carries
coworker names and Amazon TBA identifiers.

`dataset` decides that at issue time, mirroring `scope` (who may submit) with
what they may submit.

THE DEFAULT IS THE DECISION HERE. Existing rows become "addresses" rather than
something permissive, which is the whole point: a migration that preserves the
property being removed is a migration that changed nothing. The live campaign
was issued for the address study, so this makes the stored value match the
intent it was created with, and narrows the link the moment it runs.

Self-contained by design — no import from app.* (ADR-427's lesson: a migration
that imports live code breaks the moment that code is renamed, and
`tests/test_migrations_are_self_contained.py` pins it).

Revision ID: 3a9f1116f17c
Revises: 60a2ecf2f1e0
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "3a9f1116f17c"
down_revision = "60a2ecf2f1e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_tokens",
        sa.Column(
            "dataset",
            sa.String(length=10),
            nullable=False,
            server_default="addresses",
        ),
    )
    # Indexed because every public submit resolves a token and now filters on
    # this alongside the token value.
    op.create_index(
        "ix_collection_tokens_dataset", "collection_tokens", ["dataset"]
    )


def downgrade() -> None:
    op.drop_index("ix_collection_tokens_dataset", table_name="collection_tokens")
    op.drop_column("collection_tokens", "dataset")
