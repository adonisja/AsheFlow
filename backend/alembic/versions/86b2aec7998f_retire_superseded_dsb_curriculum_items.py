"""ADR-262: retire the three superseded DSB curriculum items

The DSB reframe changed two topic TITLES, and the seed script's identity key is
(company_id, day_number, topic_title). A retitled item is therefore a NEW row —
the corrected version was inserted while the superseded one stayed behind, so
both were live at once and a trainee could be taught the wrong framing.

The worst of them asserted "Delivered to Household Member is not a valid
delivery method", which is factually wrong: OTP packages REQUIRE it. See
docs/SCORECARD_METRICS_RESEARCH.md "DSB" and the LEARNING_GUIDE lesson
"A metric that fires conditionally cannot be taught as a prohibition".

Deletes the superseded rows and any TrainingTask rows generated from them that
are still open. Completed tasks are LEFT ALONE — they are a historical record
of what was actually taught, and rewriting history would misrepresent a
trainer's sign-off.

Revision ID: 86b2aec7998f
Revises: 83e4cd66249c
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "86b2aec7998f"
down_revision = "83e4cd66249c"
branch_labels = None
depends_on = None


# Exact titles of the superseded items, as seeded before the reframe.
_RETIRED_TITLES = [
    "DSB: simultaneous deliveries — what it means, when to use, when NOT to use",
    "DSB: delivered to household member — what it means, why invalid, what to do instead",
    "DSB: delivered >50 meters — GeoPin wrong location, Airplane mode explained",
    "Keys to Success: NEVER mark 'household member'",
]


def upgrade() -> None:
    conn = op.get_bind()

    # Drop open tasks generated from the retired topics. Completed work stays:
    # it records what a trainer actually covered on a given day.
    conn.execute(
        sa.text(
            "DELETE FROM training_tasks "
            "WHERE topic_title = ANY(:titles) "
            "  AND (is_completed IS NULL OR is_completed = false)"
        ),
        {"titles": _RETIRED_TITLES},
    )

    conn.execute(
        sa.text("DELETE FROM training_curriculums WHERE topic_title = ANY(:titles)"),
        {"titles": _RETIRED_TITLES},
    )


def downgrade() -> None:
    # Deliberately not restored. These rows carried a factually incorrect
    # instruction; re-seeding them on downgrade would reintroduce the defect.
    # Re-run scripts/seed_training_curriculum.py to repopulate the corrected set.
    pass
