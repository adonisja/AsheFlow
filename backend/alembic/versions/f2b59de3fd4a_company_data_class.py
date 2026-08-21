"""companies.data_class — live | seed | demo (ADR-280)

Nothing in the database said which rows were real. Staging carries 1,194,365
delivery stops and 46,889 routes, essentially all script-generated, with no
column recording that.

Two concrete failures this closes:

1. A measurement over a mixed table is not a measurement. Reading segment_ids
   coverage for ADR-279 gave 44/46,889 (0.09%) — apparently a broken feature.
   580 of the recent rows were backdated by seed_history_backfill.py, which
   never writes segment_ids, so they structurally cannot carry the field being
   measured. The true figure was 44/44 on the one day with a real sort. Only
   noticing a shared created_at second caught it.

2. Four seed scripts pick their target with a bare `db.query(Company).first()`
   — no filter, unordered — and seed_training_curriculum.py defaults to EVERY
   company. On a database with a live tenant, either writes fabricated
   operational history into real customer data, and every row would be
   well-formed and correctly company-scoped, so nothing downstream would flag
   it.

Default is 'live' (D2): a company created by a path that does not know about
this column is treated as real. The failure mode must be "a seeded tenant was
mistakenly protected", never "a live tenant was mistakenly wiped".

Backfill: the two existing companies are both script-generated (ADR-108's
two-company isolation seed), so both become 'seed'. Guarded on row count — on
any database with more than those two, the backfill is skipped and the safe
'live' default stands, because this migration cannot know which of them are
real.

Revision ID: f2b59de3fd4a
Revises: 03f64a885658
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "f2b59de3fd4a"
down_revision = "03f64a885658"
branch_labels = None
depends_on = None

# The two companies ADR-108's seed creates. Named explicitly rather than
# "update every row" so this cannot mislabel a real tenant.
_KNOWN_SEED_SLUGS = ("dsp-test", "rival-dsp")


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "data_class",
            sa.String(length=10),
            nullable=False,
            server_default="live",
        ),
    )
    # Indexed because it becomes a predicate on analytics joins and on the
    # seed-target lookup, not just stored state.
    op.create_index("ix_companies_data_class", "companies", ["data_class"])

    conn = op.get_bind()
    # Only reclassify the two known seed tenants, and only when they are the
    # ONLY companies present. A database with others may hold a real tenant,
    # and this migration has no way to tell which — so it leaves everything
    # 'live' and lets an operator classify deliberately.
    total = conn.execute(sa.text("SELECT count(*) FROM companies")).scalar()
    if total is not None and total <= len(_KNOWN_SEED_SLUGS):
        conn.execute(
            sa.text(
                "UPDATE companies SET data_class = 'seed' WHERE slug = ANY(:slugs)"
            ),
            {"slugs": list(_KNOWN_SEED_SLUGS)},
        )


def downgrade() -> None:
    op.drop_index("ix_companies_data_class", table_name="companies")
    op.drop_column("companies", "data_class")
