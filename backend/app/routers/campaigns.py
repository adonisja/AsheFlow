"""Campaign endpoints (ADR-485 D5/D6/D7).

Two audiences, two gates:

  * **management, admin** — design a campaign, open and close runs, read
    results. Same gate as the driver survey it replaces (D7): managers are the
    people who know what to ask and when, and splitting design from activation
    would put the question set one approval away from the person running the
    shift.
  * **field roles** — their own open runs, and their own submissions. Never a
    role list: who may answer is decided by the SCOPING INVARIANT (D3), not by
    a gate. The old survey gated on ["trainer", "walker"], which excluded every
    driver from ever responding about anyone and never excluded the subject
    from their own review.

WHAT IS NOT HERE
================
Scheduling (D12), notification fan-out, the attribution request flow (D13) and
the results surface (D15) are separate changes. This is the minimum that makes
a campaign answerable: open a run, see what you owe, submit it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.campaign import (
    VALID_QUESTION_KINDS, VALID_SUBJECT_ROLES, Campaign, CampaignAnswer,
    CampaignQuestion, CampaignResponse, CampaignRun,
)
from app.models.employee import Employee
from app.services.audit import write_audit
from app.services.campaign_scope import (
    assignments_without_a_subject, may_answer_about, respondents_for,
    subjects_for,
)
from app.services.campaign_results import (
    campaign_trend, free_text, non_respondents, question_rollups, response_rate,
    subject_rollups,
)
from app.services.company_config import get_company_config
from app.services.local_date import company_datetime, company_today, company_tz

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

allow_management = RoleChecker(["management", "admin"])


# ---------------------------------------------------------------------------
# Schemas
#
# ADR-115 D9: no Any, no bare dict, bounds on every field. A request body is
# attacker-controlled input, and these carry free text straight to a JSONB-
# adjacent store and into an operator's UI.
# ---------------------------------------------------------------------------

class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1, max_length=300)
    kind: str = Field(..., max_length=10)
    required: bool = True
    scale_min: Optional[int] = Field(None, ge=0, le=100)
    scale_max: Optional[int] = Field(None, ge=0, le=100)
    # A choice list, not an arbitrary blob: bounded in both directions, so a
    # question cannot carry a thousand options or a 10kB one.
    choices: Optional[List[str]] = Field(None, max_length=12)


class CampaignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=120)
    subject_role: str = Field(..., max_length=20)
    questions: List[QuestionIn] = Field(..., min_length=1, max_length=50)


class QuestionOut(BaseModel):
    id: uuid.UUID
    position: int
    prompt: str
    kind: str
    required: bool
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    choices: Optional[List[str]] = None
    model_config = {"from_attributes": True}


class CampaignOut(BaseModel):
    id: uuid.UUID
    label: str
    subject_role: str
    status: str
    questions: List[QuestionOut] = []
    model_config = {"from_attributes": True}


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Optional[str] = Field(None, max_length=10)   # YYYY-MM-DD; default today


class RunOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_label: str
    date: str
    opens_at: datetime
    closes_at: datetime
    closed_at: Optional[datetime] = None
    notified_count: int
    skipped_count: int


class OpenRunOut(BaseModel):
    """What a field user sees in `my-open`.

    Carries the DATE and the TRUCK, never just the campaign name: a daily
    campaign routinely has two runs open at once (D12), and two entries reading
    "Driver Survey" with no date is the one confusion this design can produce.
    """
    run_id: uuid.UUID
    campaign_label: str
    date: str
    closes_at: datetime
    subject_id: uuid.UUID
    subject_name: str
    truck_name: Optional[str] = None
    answered: bool
    questions: List[QuestionOut]


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    bool_value: Optional[bool] = None
    int_value: Optional[int] = Field(None, ge=0, le=100)
    text_value: Optional[str] = Field(None, max_length=2000)


class ResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: uuid.UUID
    answers: List[AnswerIn] = Field(..., min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _live_questions(db: Session, campaign_id: uuid.UUID, company_id: uuid.UUID):
    """The current wording — retired rows are history, not the question set."""
    return (
        db.query(CampaignQuestion)
        .filter(
            CampaignQuestion.campaign_id == campaign_id,
            CampaignQuestion.company_id == company_id,
            CampaignQuestion.retired_at.is_(None),
        )
        .order_by(CampaignQuestion.position.asc())
        .all()
    )


def _get_campaign(db: Session, campaign_id: uuid.UUID, company_id: uuid.UUID) -> Campaign:
    c = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_id, Campaign.company_id == company_id)
        .first()
    )
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found.")
    return c


def _get_run(db: Session, run_id: uuid.UUID, company_id: uuid.UUID) -> CampaignRun:
    r = (
        db.query(CampaignRun)
        .filter(CampaignRun.id == run_id, CampaignRun.company_id == company_id)
        .first()
    )
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.")
    return r


def _is_open(run: CampaignRun, now: datetime) -> bool:
    return run.closed_at is None and run.opens_at <= now < run.closes_at


# ---------------------------------------------------------------------------
# Design (management, admin)
# ---------------------------------------------------------------------------

@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Design a campaign. The engine knows nothing about driver vs captain —
    both are ordinary rows differing only in `subject_role` (D8)."""
    if body.subject_role not in VALID_SUBJECT_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That is not a role someone can hold on a truck.",
        )

    campaign = Campaign(
        id=uuid.uuid4(),
        company_id=caller.company_id,
        label=body.label,
        subject_role=body.subject_role,
        created_by=caller.id,
    )
    db.add(campaign)
    db.flush()

    for position, q in enumerate(body.questions, start=1):
        _validate_question_shape(q)
        db.add(CampaignQuestion(
            id=uuid.uuid4(),
            company_id=caller.company_id,
            campaign_id=campaign.id,
            position=position,
            prompt=q.prompt,
            kind=q.kind,
            required=q.required,
            scale_min=q.scale_min,
            scale_max=q.scale_max,
            choices=q.choices,
        ))
    db.flush()

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="campaign.created",
        target_table="campaigns",
        target_id=str(campaign.id),
        after={"label": campaign.label, "subject_role": campaign.subject_role,
               "questions": len(body.questions)},
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_out(db, campaign)


def _validate_question_shape(q: QuestionIn) -> None:
    """The CHECK constraints, restated where a 422 can explain them.

    The database would reject these anyway — but as an IntegrityError the
    operator cannot read, on a form they just filled in.
    """
    if q.kind not in VALID_QUESTION_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"'{q.kind}' is not a question type.")
    if q.kind == "scale":
        if q.scale_min is None or q.scale_max is None or q.scale_min >= q.scale_max:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{q.prompt}' is a scale and needs a low and a high value.")
    if q.kind == "choice" and not q.choices:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{q.prompt}' is a choice question and needs at least one option.")


def _campaign_out(db: Session, campaign: Campaign) -> CampaignOut:
    qs = _live_questions(db, campaign.id, campaign.company_id)
    return CampaignOut(
        id=campaign.id, label=campaign.label, subject_role=campaign.subject_role,
        status=campaign.status,
        questions=[QuestionOut.model_validate(q, from_attributes=True) for q in qs],
    )


@router.get("", response_model=List[CampaignOut])
def list_campaigns(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Campaign)
        .filter(Campaign.company_id == caller.company_id)
        .order_by(Campaign.created_at.desc())
        .all()
    )
    return [_campaign_out(db, c) for c in rows]


# ---------------------------------------------------------------------------
# Runs (management, admin)
# ---------------------------------------------------------------------------

@router.post("/{campaign_id}/runs", response_model=RunOut,
             status_code=status.HTTP_201_CREATED)
def open_run(
    campaign_id: uuid.UUID,
    body: RunIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Open a run for a date. Manual open is ALWAYS available (D12).

    Reactivation creates a NEW run rather than reopening one, which is what
    makes daily/weekly/monthly work and preserves history for comparison.
    """
    campaign = _get_campaign(db, campaign_id, caller.company_id)
    if campaign.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This campaign is archived.")

    tz = company_tz(db, caller.company_id)
    run_date = company_today(db, caller.company_id)
    if body.date:
        try:
            run_date = datetime.strptime(body.date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Date must be YYYY-MM-DD.")

    # D1: the same campaign cannot run twice for one day. The DB enforces it;
    # this turns the IntegrityError into something an operator can read.
    existing = (
        db.query(CampaignRun)
        .filter(CampaignRun.campaign_id == campaign.id,
                CampaignRun.company_id == caller.company_id,
                CampaignRun.date == run_date)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This campaign already ran on {run_date.isoformat()}.")

    if not _live_questions(db, campaign.id, caller.company_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This campaign has no questions to ask.")

    cfg = get_company_config(db, caller.company_id)
    now = datetime.now(timezone.utc)

    # D12: the daily window closes at the NEXT day's shift_start, company-local
    # — a fixed, predictable instant that does not depend on tomorrow's
    # dispatch existing yet, so a respondent can be shown a real countdown.
    if cfg is not None and cfg.shift_start is not None:
        closes_at = company_datetime(tz, run_date + timedelta(days=1), cfg.shift_start)
    else:
        closes_at = company_datetime(tz, run_date + timedelta(days=1), datetime.min.time())
    if closes_at <= now:
        closes_at = now + timedelta(hours=12)

    run = CampaignRun(
        id=uuid.uuid4(),
        company_id=caller.company_id,
        campaign_id=campaign.id,
        date=run_date,
        opens_at=now,
        closes_at=closes_at,
        opened_by=caller.id,
    )
    db.add(run)
    db.flush()

    # D16: who was asked, and which trucks had nobody to ask about. "Nobody
    # answered" and "nobody was asked" must not look the same on the results
    # page, and a rate over a quietly smaller denominator gets acted on wrongly.
    respondents = respondents_for(db, run, campaign)
    skipped = assignments_without_a_subject(db, run, campaign)
    run.notified_count = len(respondents)
    run.skipped_assignment_ids = [str(a) for a in skipped]

    if not respondents:
        # An open run that could never collect a response is indistinguishable,
        # on the results page, from one everybody ignored.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Nobody on {run_date.isoformat()} can answer this: no crew was "
            f"assigned alongside a {campaign.subject_role}.")

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="campaign.run_opened",
        target_table="campaign_runs",
        target_id=str(run.id),
        after={"campaign": campaign.label, "date": run_date.isoformat(),
               "notified": len(respondents), "skipped": len(skipped)},
    )
    db.commit()
    db.refresh(run)
    return _run_out(run, campaign.label)


def _run_out(run: CampaignRun, label: str) -> RunOut:
    return RunOut(
        id=run.id, campaign_id=run.campaign_id, campaign_label=label,
        date=run.date.isoformat(), opens_at=run.opens_at, closes_at=run.closes_at,
        closed_at=run.closed_at, notified_count=run.notified_count,
        skipped_count=len(run.skipped_assignment_ids or []),
    )


@router.post("/runs/{run_id}/close", response_model=RunOut)
def close_run(
    run_id: uuid.UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Stop collecting now. Always available (D12).

    `closed_at` is separate from `closes_at` for ADR-423's reason: both stop
    submissions, only one means somebody decided something.
    """
    run = _get_run(db, run_id, caller.company_id)
    # One-way stamp, 409-guarded (ADR-115 D2).
    if run.closed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This run is already closed.")

    run.closed_at = datetime.now(timezone.utc)
    run.closed_by = caller.id
    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="campaign.run_closed",
        target_table="campaign_runs",
        target_id=str(run.id),
        after={"closed_at": run.closed_at.isoformat()},
    )
    db.commit()
    db.refresh(run)
    campaign = _get_campaign(db, run.campaign_id, caller.company_id)
    return _run_out(run, campaign.label)


@router.get("/runs", response_model=List[RunOut])
def list_runs(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CampaignRun, Campaign.label)
        .join(Campaign, Campaign.id == CampaignRun.campaign_id)
        .filter(CampaignRun.company_id == caller.company_id)
        .order_by(CampaignRun.date.desc())
        .limit(200)
        .all()
    )
    return [_run_out(r, label) for r, label in rows]


# ---------------------------------------------------------------------------
# Field: what do I owe, and submitting it
#
# NO ROLE GATE. Who may answer is decided by the scoping invariant (D3).
# ---------------------------------------------------------------------------

@router.get("/my-open", response_model=List[OpenRunOut])
def my_open_runs(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """The runs this caller may answer right now (D6).

    The nav entry renders when this is non-empty, and the badge is its length —
    which is what makes a campaign's nav live only while it is live, in a nav
    config that otherwise knows only roles and feature flags.
    """
    now = datetime.now(timezone.utc)
    runs = (
        db.query(CampaignRun, Campaign)
        .join(Campaign, Campaign.id == CampaignRun.campaign_id)
        .filter(
            CampaignRun.company_id == caller.company_id,
            CampaignRun.closed_at.is_(None),
            CampaignRun.opens_at <= now,
            CampaignRun.closes_at > now,
        )
        .order_by(CampaignRun.date.asc())
        .all()
    )

    out: List[OpenRunOut] = []
    for run, campaign in runs:
        for elig in subjects_for(db, run, campaign, caller.id):
            answered = (
                db.query(CampaignResponse.id)
                .filter(CampaignResponse.run_id == run.id,
                        CampaignResponse.company_id == caller.company_id,
                        CampaignResponse.respondent_id == caller.id,
                        CampaignResponse.subject_id == elig.subject_id)
                .first() is not None
            )
            subject = db.query(Employee).filter(
                Employee.id == elig.subject_id,
                Employee.company_id == caller.company_id,
            ).first()
            out.append(OpenRunOut(
                run_id=run.id,
                campaign_label=campaign.label,
                date=run.date.isoformat(),
                closes_at=run.closes_at,
                subject_id=elig.subject_id,
                subject_name=subject.name if subject else "Unknown",
                truck_name=_truck_name(db, elig.truck_assignment_id, caller.company_id),
                answered=answered,
                questions=[QuestionOut.model_validate(q, from_attributes=True)
                           for q in _live_questions(db, campaign.id, caller.company_id)],
            ))
    return out


def _truck_name(db: Session, assignment_id, company_id) -> Optional[str]:
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment

    row = (
        db.query(Truck.name)
        .join(TruckAssignment, TruckAssignment.truck_id == Truck.id)
        .filter(TruckAssignment.id == assignment_id,
                TruckAssignment.company_id == company_id)
        .first()
    )
    return row[0] if row else None


@router.post("/runs/{run_id}/respond", status_code=status.HTTP_201_CREATED)
def submit_response(
    run_id: uuid.UUID,
    body: ResponseIn,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Submit one response about one subject.

    The client NAMES a subject; this decides whether that is allowed. D3 is
    re-run here rather than trusting the list the client was shown.
    """
    run = _get_run(db, run_id, caller.company_id)
    campaign = _get_campaign(db, run.campaign_id, caller.company_id)

    now = datetime.now(timezone.utc)
    if not _is_open(run, now):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This closed before you answered.")

    elig = may_answer_about(db, run, campaign, caller.id, body.subject_id)
    if elig is None:
        # 404, not 403: "you may not answer about this person" confirms the run
        # exists and that someone else was asked, which is a disclosure when the
        # subject is a colleague.
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "There is nothing for you to answer here.")

    questions = {q.id: q for q in _live_questions(db, campaign.id, caller.company_id)}
    _validate_answers(body, questions)

    response = CampaignResponse(
        id=uuid.uuid4(),
        company_id=caller.company_id,
        run_id=run.id,
        respondent_id=caller.id,
        subject_id=elig.subject_id,
        truck_assignment_id=elig.truck_assignment_id,
    )
    db.add(response)
    db.flush()

    for a in body.answers:
        q = questions[a.question_id]
        db.add(CampaignAnswer(
            id=uuid.uuid4(),
            company_id=caller.company_id,
            response_id=response.id,
            question_id=q.id,
            bool_value=a.bool_value if q.kind == "bool" else None,
            int_value=a.int_value if q.kind in ("scale", "choice") else None,
            text_value=a.text_value if q.kind == "text" else None,
        ))
    db.flush()

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="campaign.response_submitted",
        target_table="campaign_responses",
        target_id=str(response.id),
        # The ANSWERS are deliberately absent: an audit row is a record that
        # something happened, and copying a colleague review into it would put
        # the content somewhere D13's attribution gate does not reach.
        after={"run": str(run.id), "campaign": campaign.label},
    )
    db.commit()
    return {"id": str(response.id), "submitted": True}


def _validate_answers(body: ResponseIn, questions: dict) -> None:
    """Each answer against ITS OWN question, never the shape that arrived."""
    seen = set()
    for a in body.answers:
        q = questions.get(a.question_id)
        if q is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "That question is not part of this campaign.")
        if a.question_id in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"'{q.prompt}' was answered twice.")
        seen.add(a.question_id)

        if q.kind == "bool" and a.bool_value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"'{q.prompt}' needs a yes or no.")
        if q.kind == "scale":
            if a.int_value is None or not (q.scale_min <= a.int_value <= q.scale_max):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"'{q.prompt}' takes a number from {q.scale_min} to {q.scale_max}.")
        if q.kind == "choice":
            options = q.choices or []
            if a.int_value is None or not (0 <= a.int_value < len(options)):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"'{q.prompt}' needs one of the listed options.")
        if q.kind == "text" and q.required and not (a.text_value or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"'{q.prompt}' needs an answer.")

    missing = [q.prompt for q in questions.values()
               if q.required and q.id not in seen]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Still needed: {', '.join(missing)}.")


# ---------------------------------------------------------------------------
# Results (management, admin) — ADR-485 D15
#
# Answers come back ANONYMOUS. Attribution is D13's approved, audited exception
# and is not built yet, so there is currently no way to see who said what.
# ---------------------------------------------------------------------------

class QuestionRollupOut(BaseModel):
    question_id: uuid.UUID
    prompt: str
    kind: str
    position: int
    answered: int
    yes: Optional[int] = None
    mean: Optional[float] = None
    option_counts: Optional[List[int]] = None
    choices: Optional[List[str]] = None


class SubjectRollupOut(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    truck_name: Optional[str] = None
    expected: int
    responded: int


class FreeTextOut(BaseModel):
    prompt: str
    text: str


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str


class RunDetailOut(BaseModel):
    run: RunOut
    responded: int
    expected: int
    questions: List[QuestionRollupOut]
    subjects: List[SubjectRollupOut]
    # Unattributed (D13). The subject never sees any of this (D5).
    free_text: List[FreeTextOut]
    # Named, deliberately: chasing a missing response needs a name, and "did
    # not answer" is not an opinion about anybody.
    not_answered: List[PersonOut]


class TrendPointOut(BaseModel):
    run_id: uuid.UUID
    date: str
    responded: int
    expected: int
    per_question: dict[str, Optional[float]]


@router.get("/runs/{run_id}/results", response_model=RunDetailOut)
def run_results(
    run_id: uuid.UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """What happened on this day (D15).

    The page a manager opens the morning after. Read-only, management+admin
    only — D5 is unconditional: the subject never sees responses about them,
    and this endpoint is the reason that has to be enforced by the gate rather
    than by the UI.
    """
    run = _get_run(db, run_id, caller.company_id)
    campaign = _get_campaign(db, run.campaign_id, caller.company_id)

    responded, expected = response_rate(db, run, campaign)
    rollups = question_rollups(db, run)

    # Attach the option labels so the client renders counts against names
    # without a second round trip. The COUNTS are index-aligned (D2), so the
    # labels are resolved here, at read time, from the live question row.
    questions = {q.id: q for q in _live_questions(db, campaign.id, caller.company_id)}
    out_questions = [
        QuestionRollupOut(
            question_id=r.question_id, prompt=r.prompt, kind=r.kind,
            position=r.position, answered=r.answered, yes=r.yes, mean=r.mean,
            option_counts=r.option_counts,
            choices=(questions[r.question_id].choices
                     if r.question_id in questions else None),
        )
        for r in rollups
    ]

    return RunDetailOut(
        run=_run_out(run, campaign.label),
        responded=responded,
        expected=expected,
        questions=out_questions,
        subjects=[SubjectRollupOut(**s._asdict()) for s in
                  subject_rollups(db, run, campaign)],
        free_text=[FreeTextOut(prompt=p, text=t) for p, t in free_text(db, run)],
        not_answered=[PersonOut(id=i, name=n) for i, n in
                      non_respondents(db, run, campaign)],
    )


@router.get("/{campaign_id}/trend", response_model=List[TrendPointOut])
def campaign_trend_endpoint(
    campaign_id: uuid.UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Is this getting better (D15).

    A falling response rate is the leading indicator that a campaign has become
    noise, and it is the number that should decide whether to renew it at the
    end of a schedule (D12).
    """
    campaign = _get_campaign(db, campaign_id, caller.company_id)
    return [
        TrendPointOut(
            run_id=p.run_id, date=p.date, responded=p.responded,
            expected=p.expected,
            per_question={str(k): v for k, v in p.per_question.items()},
        )
        for p in campaign_trend(db, campaign)
    ]
