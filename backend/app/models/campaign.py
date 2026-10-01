"""Campaign system — admin-designed surveys scoped to a day on a truck (ADR-485).

Replaces `driver_survey.py`, whose questions were four hardcoded Boolean columns
(`routes_organized`, `anchor_point_location`, `supplies_ready`,
`driver_support`). Adding a fifth meant a migration, a schema change, a router
change and a frontend change — which is the thing being removed.

Seven tables:

    Campaign              the template; outlives every run it produces
     ├─ CampaignQuestion  one question, typed; superseded rather than edited
     ├─ CampaignSchedule  optional; a campaign with none is opened by hand
     └─ CampaignRun       one activation, for one date
         └─ CampaignResponse   one respondent's submission about one subject
             └─ CampaignAnswer one answer to one question

plus AttributionRequest, the gated path from anonymous results to attributed
ones (D13).

THE INVARIANT (D3) is not expressed here, because it cannot be: a response is
valid only if respondent and subject shared ONE assignment on the RUN's date.
That is a self-join on `assignment_members` resolved at submit time, and
`CampaignResponse.subject_id` stores its answer so a later crew change cannot
retroactively re-point an existing review.
"""
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base

# The assignment SLOT namespace (ADR-256), not Employee.role. A captain-titled
# employee slotted as a walker for the day is a walker here — which is why a
# campaign's subject_role is matched against AssignmentMember.role.
VALID_SUBJECT_ROLES = (
    "driver", "trainer", "trainee", "walker", "captain", "driver_trainee",
)
VALID_QUESTION_KINDS = ("bool", "scale", "text", "choice")
VALID_SCHEDULE_MODES = ("daily", "weekly_fixed", "weekly_random", "monthly")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """A CHECK body derived from the tuple, never retyped beside it.

    Two lists that must agree are two lists that will not (ADR-468).
    """
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Campaign(Base):
    """The template. Outlives every run it produces."""
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_campaign_status"),
        CheckConstraint(_in_list("subject_role", VALID_SUBJECT_ROLES),
                        name="ck_campaign_subject_role"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)

    label        = Column(String(120), nullable=False)
    # Which slot on the assignment is reviewed. The engine knows nothing about
    # "driver survey" vs "captain survey" (D8) — both are ordinary rows.
    subject_role = Column(String(20), nullable=False)

    status       = Column(String(10), nullable=False, server_default="active")
    created_by   = Column(UUID(as_uuid=True),
                          ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False,
                          server_default=func.now())


class CampaignQuestion(Base):
    """One question. Frozen the moment it has an answer (D2).

    Editing the prompt of a question people have already answered silently
    rewrites what their answer meant, so a PATCH on an answered question
    retires this row and inserts a replacement at the same position.
    """
    __tablename__ = "campaign_questions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "position", "retired_at",
                         name="uq_campaign_question_position"),
        CheckConstraint(_in_list("kind", VALID_QUESTION_KINDS),
                        name="ck_campaign_question_kind"),
        # A scale without bounds, or a choice without choices, is a question
        # nobody can answer. Caught by the DB, not by remembering.
        CheckConstraint(
            "(kind <> 'scale') OR (scale_min IS NOT NULL AND scale_max IS NOT NULL"
            " AND scale_min < scale_max)",
            name="ck_campaign_question_scale_bounds"),
        CheckConstraint("(kind <> 'choice') OR (choices IS NOT NULL)",
                        name="ck_campaign_question_choices"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id   = Column(UUID(as_uuid=True),
                           ForeignKey("campaigns.id", ondelete="CASCADE"),
                           nullable=False, index=True)

    position      = Column(Integer, nullable=False)
    prompt        = Column(String(300), nullable=False)
    kind          = Column(String(10), nullable=False)
    required      = Column(Boolean, nullable=False, server_default="true")

    scale_min     = Column(Integer, nullable=True)
    scale_max     = Column(Integer, nullable=True)
    # The ONE JSONB here, and deliberately: this is question DEFINITION written
    # by an admin through a validated request model, never answer DATA from a
    # respondent. ADR-115 D9 is about the trust boundary, and this is not it.
    choices       = Column(JSONB, nullable=True)

    # NULL while this is the live wording. Set when an edit supersedes it.
    retired_at    = Column(DateTime(timezone=True), nullable=True)
    supersedes_id = Column(UUID(as_uuid=True),
                           ForeignKey("campaign_questions.id", ondelete="SET NULL"),
                           nullable=True)


class CampaignSchedule(Base):
    """Optional. A campaign with no schedule is opened by hand (D12).

    Every mode is bounded, so a campaign somebody set up and forgot stops
    asking on its own — and the end is announced, because a schedule that
    lapses silently is how a company finds out in autumn that nobody has been
    surveyed since spring.
    """
    __tablename__ = "campaign_schedules"
    __table_args__ = (
        CheckConstraint(_in_list("mode", VALID_SCHEDULE_MODES),
                        name="ck_campaign_schedule_mode"),
        CheckConstraint("(mode <> 'weekly_fixed') OR (weekday BETWEEN 0 AND 6)",
                        name="ck_campaign_schedule_weekday"),
        CheckConstraint("ends_on >= starts_on", name="ck_campaign_schedule_range"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    # At most one schedule per campaign: two would race to open the same date.
    campaign_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaigns.id", ondelete="CASCADE"),
                         nullable=False, unique=True)

    mode        = Column(String(16), nullable=False)
    weekday     = Column(Integer, nullable=True)          # weekly_fixed only, 0=Mon
    starts_on   = Column(Date, nullable=False)
    ends_on     = Column(Date, nullable=False)

    # One-way stamp: the end-of-schedule notice is sent once, not every tick.
    ended_notified_at = Column(DateTime(timezone=True), nullable=True)

    created_by  = Column(UUID(as_uuid=True),
                         ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False,
                         server_default=func.now())


class CampaignRun(Base):
    """One activation, for one date."""
    __tablename__ = "campaign_runs"
    __table_args__ = (
        # The same campaign cannot run twice for one day (D1). Concurrent open
        # runs for DIFFERENT dates are allowed — D12 drops the "one open run"
        # rule, because D3 already scopes each response to its run's date.
        UniqueConstraint("campaign_id", "date", name="uq_campaign_run_date"),
        CheckConstraint("closes_at > opens_at", name="ck_campaign_run_window"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaigns.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    # THE scoping key. D3 reads this, never "today".
    date        = Column(Date, nullable=False, index=True)

    opens_at    = Column(DateTime(timezone=True), nullable=False)
    closes_at   = Column(DateTime(timezone=True), nullable=False)
    # Separate from closes_at for ADR-423's reason: both stop submissions, only
    # one means somebody decided something. One-way, 409-guarded.
    closed_at   = Column(DateTime(timezone=True), nullable=True)
    closed_by   = Column(UUID(as_uuid=True),
                         ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    opened_by   = Column(UUID(as_uuid=True),
                         ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    # NULL when opened by hand; set when a schedule produced it.
    schedule_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaign_schedules.id", ondelete="SET NULL"),
                         nullable=True)

    # How many people were asked, recorded at open. "Nobody answered" and
    # "nobody was asked" must not look the same on the results page (D15).
    notified_count = Column(Integer, nullable=False, server_default="0")
    # Assignments on this date with no member in the subject role (D16) — a
    # truck running without a captain is an ordinary state, and a response rate
    # computed over a quietly smaller denominator gets acted on wrongly.
    skipped_assignment_ids = Column(JSONB, nullable=False, server_default="[]")


class CampaignResponse(Base):
    """One respondent's submission, about one subject, on one run."""
    __tablename__ = "campaign_responses"
    __table_args__ = (
        # A second POST is a 409, not a second opinion.
        UniqueConstraint("run_id", "respondent_id", name="uq_campaign_response"),
        # D3's last clause, restated where the DB can enforce it.
        CheckConstraint("respondent_id <> subject_id",
                        name="ck_campaign_response_not_self"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    run_id        = Column(UUID(as_uuid=True),
                           ForeignKey("campaign_runs.id", ondelete="CASCADE"),
                           nullable=False, index=True)

    respondent_id = Column(UUID(as_uuid=True),
                           ForeignKey("employees.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # Who this is ABOUT. Resolved by D3 at submit and STORED, so a later change
    # to the assignment cannot retroactively re-point an existing review.
    subject_id    = Column(UUID(as_uuid=True),
                           ForeignKey("employees.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # The assignment that made the pair valid — kept for the per-truck rollup
    # (D15) and so the scoping decision is auditable after the fact.
    truck_assignment_id = Column(UUID(as_uuid=True),
                                 ForeignKey("truck_assignments.id", ondelete="SET NULL"),
                                 nullable=True)

    submitted_at  = Column(DateTime(timezone=True), nullable=False,
                           server_default=func.now())


class CampaignAnswer(Base):
    """One answer to one question. Typed columns, never a JSONB blob (D2)."""
    __tablename__ = "campaign_answers"
    __table_args__ = (
        # One answer per question per response: a double submit cannot become
        # two contradictory answers.
        UniqueConstraint("response_id", "question_id", name="uq_campaign_answer"),
        # Exactly one value column is populated. An answer with none is a silent
        # skip of a required question; one with two is ambiguous at read time.
        #
        # CASE rather than Postgres's `::int`: five test files call
        # Base.metadata.create_all on SQLite, which rejects the cast with
        # "unrecognized token: :" and takes 121 unrelated tests with it. The
        # CASE form is standard SQL and was verified to behave identically.
        CheckConstraint(
            "(CASE WHEN bool_value IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN int_value  IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_campaign_answer_exactly_one_value"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    response_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaign_responses.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    # RESTRICT, not CASCADE: deleting a question that has answers would orphan
    # them. Retirement (retired_at) is how a question goes away.
    question_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaign_questions.id", ondelete="RESTRICT"),
                         nullable=False, index=True)

    bool_value  = Column(Boolean, nullable=True)
    # scale, and the choice INDEX. Storing the index rather than the label means
    # renaming an option later cannot silently rewrite history.
    int_value   = Column(Integer, nullable=True)
    text_value  = Column(Text, nullable=True)

    # D15 sentiment: triage only, on the ANSWER, never on anybody's record.
    # NULL is ordinary — scoring runs after close and fails silently.
    sentiment            = Column(String(10), nullable=True)
    sentiment_scored_at  = Column(DateTime(timezone=True), nullable=True)
    # D14: roster names rewritten to roles 7 days after the run closes.
    names_redacted_at    = Column(DateTime(timezone=True), nullable=True)


class AttributionRequest(Base):
    """A manager asks an admin to unlock who said what, for ONE run (D13).

    A self-serve reveal is anonymity in name only: a manager who can click
    through whenever they like is a manager respondents must assume is reading
    their name.
    """
    __tablename__ = "campaign_attribution_requests"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    # ONE run. A standing grant over a campaign is the self-serve reveal with
    # extra steps.
    run_id       = Column(UUID(as_uuid=True),
                          ForeignKey("campaign_runs.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    requested_by = Column(UUID(as_uuid=True),
                          ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    # >= 10 words, enforced at the request schema: the smallest bar that makes
    # "following up" impossible to type.
    reason       = Column(Text, nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False,
                          server_default=func.now())

    # One-way stamps, each 409-guarded. Only an admin approves, never their own.
    approved_by  = Column(UUID(as_uuid=True),
                          ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    approved_at  = Column(DateTime(timezone=True), nullable=True)
    denied_at    = Column(DateTime(timezone=True), nullable=True)
    # A grant that never closes is a permission, not an exception.
    expires_at   = Column(DateTime(timezone=True), nullable=True)
