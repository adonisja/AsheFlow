"""ADR-419: workload_other, and not_applicable becomes other

Adds the free-text field behind the `other` workload tag, and renames the
`not_applicable` tag to `other` in existing rows.

Revision ID: 9c32a580c1d3
Revises: 46f04059c09f
"""
from alembic import op
import sqlalchemy as sa

revision = "9c32a580c1d3"
down_revision = "46f04059c09f"
branch_labels = None
depends_on = None

_TABLES = (
    "building_profiles",
    "building_profile_library",
    "collected_address_profiles",
)


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("workload_other", sa.String(length=200),
                                   nullable=True))

        # `not_applicable` and `other` mean the same thing to a reader — "the
        # four tags do not describe this door" — so existing rows are renamed
        # rather than invalidated. They keep a NULL `workload_other`, which is
        # correct: nobody was ever asked for the text, and inventing one would
        # be worse than leaving it empty.
        op.execute(sa.text(
            f"UPDATE {t} SET workloads = '[\"other\"]'::jsonb "
            f"WHERE workloads @> '[\"not_applicable\"]'::jsonb"
        ))


def downgrade() -> None:
    for t in _TABLES:
        op.execute(sa.text(
            f"UPDATE {t} SET workloads = '[\"not_applicable\"]'::jsonb "
            f"WHERE workloads @> '[\"other\"]'::jsonb"
        ))
        op.drop_column(t, "workload_other")
