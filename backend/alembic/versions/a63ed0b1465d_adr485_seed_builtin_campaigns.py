"""ADR-485 D8: the built-in campaigns, for companies that already exist.

`seed_campaigns_for` runs at company creation from now on. This gives the
same two campaigns to every company created before it.

IDEMPOTENT by (company_id, subject_role), not by label: a tenant who renamed
"Driver Survey" has one driver campaign, and re-running must not give them a
second.

The question text is DUPLICATED from campaign_seeds.py rather than imported. A
migration that imports live code breaks the moment that code is renamed
(ADR-427), and these rows are a historical fact about what was seeded on this
date -- editing the service later must not retroactively change them.

Revision ID: a63ed0b1465d
Revises: f5303d1a3726
Create Date: 2026-10-02
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "a63ed0b1465d"
down_revision = "f5303d1a3726"
branch_labels = None
depends_on = None

_SEEDS = [
    ("Driver Survey", "driver", [
        ("Were the routes organised?", "bool", True),
        ("Was the anchor point where it said it would be?", "bool", True),
        ("Were supplies ready and available?", "bool", True),
        ("Did the driver support the crew?", "bool", True),
        ("Anything else? (optional)", "text", False),
    ]),
    ("Captain Survey", "captain", [
        ("Were the routes available on time?", "bool", True),
        ("Were your blocks next to each other, or were you sent back and forth?",
         "bool", True),
        ("Was the work distributed fairly?", "bool", True),
        ("Were misroutes and RTS handled quickly, without holding you up?",
         "bool", True),
        ("Could you reach a captain when you needed them?", "bool", True),
        ("Anything else? (optional)", "text", False),
    ]),
]


def upgrade() -> None:
    conn = op.get_bind()
    companies = conn.execute(sa.text("SELECT id FROM companies")).fetchall()

    seeded = 0
    for (company_id,) in companies:
        for label, subject_role, questions in _SEEDS:
            exists = conn.execute(
                sa.text("SELECT 1 FROM campaigns WHERE company_id = :c "
                        "AND subject_role = :r LIMIT 1"),
                {"c": company_id, "r": subject_role},
            ).first()
            if exists:
                continue

            campaign_id = uuid.uuid4()
            conn.execute(
                sa.text("INSERT INTO campaigns (id, company_id, label, subject_role, "
                        "status) VALUES (:i, :c, :l, :r, 'active')"),
                {"i": campaign_id, "c": company_id, "l": label, "r": subject_role},
            )
            for position, (prompt, kind, required) in enumerate(questions, start=1):
                conn.execute(
                    sa.text("INSERT INTO campaign_questions (id, company_id, "
                            "campaign_id, position, prompt, kind, required) "
                            "VALUES (:i, :c, :k, :p, :t, :n, :q)"),
                    {"i": uuid.uuid4(), "c": company_id, "k": campaign_id,
                     "p": position, "t": prompt, "n": kind, "q": required},
                )
            seeded += 1

    print(f"ADR-485 D8: seeded {seeded} built-in campaign(s) across "
          f"{len(companies)} company/companies")


def downgrade() -> None:
    """Removes ONLY campaigns that still look exactly as seeded.

    A tenant who edited the questions, renamed the campaign, or ran it has made
    it theirs, and a downgrade must not delete their work. The ON DELETE
    CASCADE from campaigns would take the questions, the runs and every
    response with it.
    """
    conn = op.get_bind()
    for label, subject_role, questions in _SEEDS:
        conn.execute(
            sa.text("""
                DELETE FROM campaigns c
                WHERE c.label = :l
                  AND c.subject_role = :r
                  AND NOT EXISTS (SELECT 1 FROM campaign_runs r WHERE r.campaign_id = c.id)
                  AND (SELECT count(*) FROM campaign_questions q
                       WHERE q.campaign_id = c.id) = :n
            """),
            {"l": label, "r": subject_role, "n": len(questions)},
        )
