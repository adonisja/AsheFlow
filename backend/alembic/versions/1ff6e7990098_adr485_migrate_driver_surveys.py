"""ADR-485 D17: move the driver survey into campaigns, then drop it.

The old tables held 0 rows in prod and 0 in staging (re-verified 2026-10-02,
both environments, via the running containers). That is a fact about two
databases at one moment, not a property of the schema, so this is written as
though rows exist.

THE MAPPING

Almost everything is direct, and the ORIGINAL UUIDs ARE KEPT -- any audit row
or link that already names a survey still resolves after the move.

    driver_surveys.id          -> campaign_runs.id
    .company_id, .date         -> direct
    .created_by                -> .opened_by
    .created_at                -> .opens_at
    (derived)                  -> .closes_at   = local midnight of date+1
    (derived)                  -> .campaign_id = the seeded driver campaign

    driver_survey_responses.id -> campaign_responses.id
    .survey_id                 -> .run_id
    .respondent_id, .truck_assignment_id, .submitted_at -> direct
    (derived)                  -> .subject_id  = the driver on that assignment

    routes_organized, anchor_point_location, supplies_ready, driver_support
                               -> campaign_answers.bool_value, questions 1-4
    notes                      -> campaign_answers.text_value, question 5

`notes` is SKIPPED when NULL rather than written as an empty string: D2's
exactly-one-value constraint rejects a row with no value set, and an empty
text_value would claim somebody answered a question they left blank.

IT REFUSES TO GUESS

subject_id is not in the old schema. It is recovered from the assignment, and
truck_assignment_id is ondelete="SET NULL" -- so for a response whose
assignment was deleted there is no way to know which truck, and therefore no
way to know which driver. company_id + date narrows it to every driver working
that day, which is not an answer.

Picking one would attribute a review to somebody who was never reviewed: a
silent, permanent, person-level falsehood. A failed deploy is cheaper.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: 1ff6e7990098
Revises: a63ed0b1465d
Create Date: 2026-10-02
"""
import uuid
from datetime import timedelta

from alembic import op
import sqlalchemy as sa

revision = "1ff6e7990098"
down_revision = "a63ed0b1465d"
branch_labels = None
depends_on = None

# Old column -> the seeded question's position (D8 seeds these 1..5 in order).
_BOOL_COLUMNS = [
    ("routes_organized", 1),
    ("anchor_point_location", 2),
    ("supplies_ready", 3),
    ("driver_support", 4),
]
_NOTES_POSITION = 5


def upgrade() -> None:
    conn = op.get_bind()

    exists = conn.execute(sa.text(
        "SELECT to_regclass('public.driver_surveys') IS NOT NULL")).scalar()
    if not exists:
        return

    surveys = conn.execute(sa.text(
        "SELECT id, company_id, date, created_by, created_at FROM driver_surveys"
    )).fetchall()

    if surveys:
        _refuse_unmappable_responses(conn)
        _migrate(conn, surveys)

    op.drop_table("driver_survey_responses")
    op.drop_table("driver_surveys")


def _refuse_unmappable_responses(conn) -> None:
    """Abort before writing anything if any subject cannot be resolved.

    Catches two shapes with one query: the assignment was deleted (SET NULL),
    and the assignment exists but has no driver row -- a truck that ran without
    one. Both are unresolvable for the same reason.
    """
    orphans = conn.execute(sa.text("""
        SELECT count(*) FROM driver_survey_responses r
        LEFT JOIN assignment_members am
               ON am.assignment_id = r.truck_assignment_id
              AND am.role = 'driver'
        WHERE am.employee_id IS NULL
    """)).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} driver survey response(s) cannot be mapped to a "
            f"subject: their truck assignment was deleted, or that truck ran "
            f"without a driver, so who the review was ABOUT is unrecoverable. "
            f"Export them, decide whether to keep them as unattributed "
            f"history, then delete those rows and re-run. This migration will "
            f"not invent a subject."
        )


def _migrate(conn, surveys) -> None:
    moved_runs = moved_responses = moved_answers = 0

    for survey_id, company_id, survey_date, created_by, created_at in surveys:
        campaign_id = conn.execute(
            sa.text("SELECT id FROM campaigns WHERE company_id = :c "
                    "AND subject_role = 'driver' LIMIT 1"),
            {"c": company_id},
        ).scalar()
        if campaign_id is None:
            raise RuntimeError(
                f"company {company_id} has driver survey data but no driver "
                f"campaign to move it into. The ADR-485 D8 seed migration must "
                f"run first."
            )

        questions = {
            position: qid for qid, position in conn.execute(
                sa.text("SELECT id, position FROM campaign_questions "
                        "WHERE campaign_id = :k AND retired_at IS NULL"),
                {"k": campaign_id},
            ).fetchall()
        }

        # Local midnight of the following day. The company's own zone, not UTC:
        # ADR-129 wrote "midnight UTC" and closed a New York survey at 8pm
        # (ADR-486). A migration that reproduces the bug is not a migration.
        tz = conn.execute(
            sa.text("SELECT COALESCE(timezone, 'UTC') FROM companies WHERE id = :c"),
            {"c": company_id},
        ).scalar() or "UTC"
        closes_at = conn.execute(
            # CAST(), not `::date` -- SQLAlchemy reads `::` as the start of a
            # bind parameter and the statement fails to parse.
            sa.text("SELECT ((CAST(:d AS date) + INTERVAL '1 day') "
                    "AT TIME ZONE :tz)"),
            {"d": survey_date, "tz": tz},
        ).scalar()

        # ck_campaign_run_window requires closes_at > opens_at. A historic
        # survey was CREATED on its own date, so its close (midnight after that
        # date) is later -- but a row backfilled or corrected afterwards can
        # carry a created_at LATER than the window it belongs to. Clamp rather
        # than fail: the run is history either way, and refusing to migrate a
        # real response over a one-second ordering artefact would strand data
        # the operator cannot recover any other way.
        opens_at = created_at
        if closes_at <= opens_at:
            opens_at = closes_at - timedelta(seconds=1)

        conn.execute(
            sa.text("""
                INSERT INTO campaign_runs
                  (id, company_id, campaign_id, date, opens_at, closes_at,
                   opened_by, notified_count, skipped_assignment_ids)
                VALUES (:i, :c, :k, :d, :o, :cl, :by, 0, '[]')
            """),
            {"i": survey_id, "c": company_id, "k": campaign_id, "d": survey_date,
             "o": opens_at, "cl": closes_at, "by": created_by},
        )
        moved_runs += 1

        responses = conn.execute(
            sa.text("""
                SELECT r.id, r.company_id, r.respondent_id, r.truck_assignment_id,
                       r.submitted_at, r.routes_organized, r.anchor_point_location,
                       r.supplies_ready, r.driver_support, r.notes
                FROM driver_survey_responses r WHERE r.survey_id = :s
            """),
            {"s": survey_id},
        ).fetchall()

        for row in responses:
            (rid, rcompany, respondent, assignment, submitted,
             organised, anchor, supplies, support, notes) = row

            subject = conn.execute(
                sa.text("SELECT employee_id FROM assignment_members "
                        "WHERE assignment_id = :a AND company_id = :c "
                        "AND role = 'driver' LIMIT 1"),
                {"a": assignment, "c": rcompany},
            ).scalar()
            # _refuse_unmappable_responses already proved this resolves.

            conn.execute(
                sa.text("""
                    INSERT INTO campaign_responses
                      (id, company_id, run_id, respondent_id, subject_id,
                       truck_assignment_id, submitted_at)
                    VALUES (:i, :c, :r, :re, :su, :ta, :st)
                """),
                {"i": rid, "c": rcompany, "r": survey_id, "re": respondent,
                 "su": subject, "ta": assignment, "st": submitted},
            )
            moved_responses += 1

            values = dict(zip(
                [c for c, _ in _BOOL_COLUMNS],
                [organised, anchor, supplies, support]))
            for column, position in _BOOL_COLUMNS:
                qid = questions.get(position)
                if qid is None:
                    continue
                conn.execute(
                    sa.text("""
                        INSERT INTO campaign_answers
                          (id, company_id, response_id, question_id, bool_value)
                        VALUES (:i, :c, :r, :q, :v)
                    """),
                    {"i": uuid.uuid4(), "c": rcompany, "r": rid, "q": qid,
                     "v": values[column]},
                )
                moved_answers += 1

            # Skipped when NULL: D2's exactly-one-value CHECK rejects a row with
            # no value, and an empty string would claim an answer nobody gave.
            if notes and notes.strip() and questions.get(_NOTES_POSITION):
                conn.execute(
                    sa.text("""
                        INSERT INTO campaign_answers
                          (id, company_id, response_id, question_id, text_value)
                        VALUES (:i, :c, :r, :q, :v)
                    """),
                    {"i": uuid.uuid4(), "c": rcompany, "r": rid,
                     "q": questions[_NOTES_POSITION], "v": notes},
                )
                moved_answers += 1

    # Verify before dropping. A count that does not match means something was
    # silently skipped, and the next statement destroys the source.
    expected_responses = conn.execute(
        sa.text("SELECT count(*) FROM driver_survey_responses")).scalar()
    if moved_responses != expected_responses:
        raise RuntimeError(
            f"moved {moved_responses} response(s) but the source holds "
            f"{expected_responses}. Refusing to drop the source tables.")

    print(f"ADR-485 D17: moved {moved_runs} run(s), {moved_responses} "
          f"response(s), {moved_answers} answer(s)")


def downgrade() -> None:
    """Recreates the tables EMPTY, and says so.

    A downgrade cannot un-migrate: the rows now live in campaign_* and deleting
    them there would destroy data collected since. This restores the SHAPE so a
    database rolled back past this point can accept writes from an older image.
    Said plainly because a downgrade that looks like a restore is worse than
    one that does not exist (ADR-440).
    """
    op.create_table(
        "driver_surveys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "date",
                            name="uq_driver_survey_company_date"),
    )
    op.create_table(
        "driver_survey_responses",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  nullable=False, index=True),
        sa.Column("survey_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("driver_surveys.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("respondent_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("truck_assignment_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("truck_assignments.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("routes_organized", sa.Boolean(), nullable=False),
        sa.Column("anchor_point_location", sa.Boolean(), nullable=False),
        sa.Column("supplies_ready", sa.Boolean(), nullable=False),
        sa.Column("driver_support", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
