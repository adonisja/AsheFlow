"""ADR-292 D3 — source on rts_packages, missing_packages, damaged_packages

Revision ID: 683ef38406fa
Revises: 425f1740dcf3
Create Date: 2026-08-24

One column on each of the three undelivered-package tables.

WHAT THIS IS NOT. It is not a synthetic-identifier scheme. The TBA on a manually
entered record is a REAL Amazon tracking number — it is printed on the package
in the walker's hand. What workforce mode lacks is the MANIFEST to match it
against, not the identifier itself. Keeping the real TBA is what leaves a
scorecard appeal answerable and a future reconciliation possible; a generated id
would be unusable outside AsheFlow.

So the schema is unchanged apart from provenance: `manifest` rows keep today's
validation (the TBA must appear on the manifest), `manual` rows accept an
unverified one.

NOT NULL with server_default 'manifest'. Every existing row came from a
manifest, so that is the truth for those rows rather than a placeholder — and a
nullable column could not distinguish "unknown provenance" from "never set",
which is the same ambiguity ADR-283 warns about for config.
"""
from alembic import op
import sqlalchemy as sa

revision = "683ef38406fa"
down_revision = "425f1740dcf3"
branch_labels = None
depends_on = None

_TABLES = ("rts_packages", "missing_packages", "damaged_packages")


def upgrade():
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("source", sa.String(length=20), nullable=False,
                      server_default="manifest"),
        )


def downgrade():
    for table in _TABLES:
        op.drop_column(table, "source")
