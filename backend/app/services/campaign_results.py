"""Reading what a campaign collected (ADR-485 D15).

THREE SURFACES, THREE QUESTIONS
===============================

  * run detail      — "what happened on this day?"
  * campaign trend  — "is this getting better?"
  * (cross-campaign is the router's list endpoint, not here)

ONE QUERY SHAPE, DIFFERENT GROUP BY. Run detail groups by question and by
subject; the trend groups by run. Keeping them one shape is what stops the
trend disagreeing with the detail about the same run — the bug this design can
most easily produce.

ANONYMITY IS STRUCTURAL, NOT A FILTER
=====================================

Every function here that returns ANSWER content omits `respondent_id` from the
SELECT entirely, rather than fetching it and dropping it later. D13 makes
attribution an approved, audited exception; a query that carries the name and
trusts a caller to discard it is one careless `.dict()` away from leaking it.

The ONE exception is deliberate and is not answer content:
`non_respondents` names people who have NOT answered. Chasing a missing
response requires knowing who to chase, and "did not answer" is not an opinion
about anybody.
"""
from __future__ import annotations

from typing import NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.campaign import (
    Campaign, CampaignAnswer, CampaignQuestion, CampaignResponse, CampaignRun,
)
from app.models.employee import Employee
from app.services.campaign_scope import respondents_for

# ADR-473's lesson, restated: a metric computed from two responses reads as a
# judgement and is noise. Below this, the trend shows the COUNT and not a rate.
MIN_RESPONSES_FOR_A_RATE = 3


class QuestionRollup(NamedTuple):
    question_id: UUID
    prompt: str
    kind: str
    position: int
    answered: int
    # bool
    yes: int | None
    # scale
    mean: float | None
    # choice — one count per option, index-aligned with the question's choices
    option_counts: list[int] | None


class SubjectRollup(NamedTuple):
    subject_id: UUID
    subject_name: str
    truck_name: str | None
    expected: int
    responded: int


def _answers_for_run(db: Session, run: CampaignRun):
    """Base: every answer on this run, joined to its question.

    NOTE the SELECT: no respondent_id, no response_id. This is the anonymity
    boundary, and it is the shape of the query rather than a later filter.
    """
    return (
        select(
            CampaignAnswer.question_id,
            CampaignQuestion.prompt,
            CampaignQuestion.kind,
            CampaignQuestion.position,
            CampaignAnswer.bool_value,
            CampaignAnswer.int_value,
            CampaignAnswer.text_value,
        )
        .join(CampaignQuestion, CampaignQuestion.id == CampaignAnswer.question_id)
        .join(CampaignResponse, CampaignResponse.id == CampaignAnswer.response_id)
        .where(
            CampaignResponse.run_id == run.id,
            # ADR-115 D1 on every table, not just the outermost one.
            CampaignResponse.company_id == run.company_id,
            CampaignAnswer.company_id == run.company_id,
            CampaignQuestion.company_id == run.company_id,
        )
    )


def question_rollups(db: Session, run: CampaignRun) -> list[QuestionRollup]:
    """Per-question summary, shaped by the question's kind.

    Rendered from the question rows, so an admin's new question needs no
    frontend change — the shape of the answer follows `kind`.
    """
    rows = db.execute(_answers_for_run(db, run)).all()

    by_q: dict[UUID, dict] = {}
    for qid, prompt, kind, position, b, i, _t in rows:
        e = by_q.setdefault(qid, {
            "prompt": prompt, "kind": kind, "position": position,
            "answered": 0, "yes": 0, "ints": [],
        })
        e["answered"] += 1
        if kind == "bool" and b:
            e["yes"] += 1
        if kind in ("scale", "choice") and i is not None:
            e["ints"].append(i)

    out: list[QuestionRollup] = []
    for qid, e in by_q.items():
        option_counts = None
        mean = None
        if e["kind"] == "choice":
            # Index-aligned with the question's `choices`, so a renamed option
            # cannot shift a past count onto a different label.
            q = db.query(CampaignQuestion).filter(
                CampaignQuestion.id == qid,
                CampaignQuestion.company_id == run.company_id,
            ).first()
            width = len(q.choices or []) if q else 0
            option_counts = [0] * width
            for v in e["ints"]:
                if 0 <= v < width:
                    option_counts[v] += 1
        elif e["kind"] == "scale" and e["ints"]:
            mean = round(sum(e["ints"]) / len(e["ints"]), 2)

        out.append(QuestionRollup(
            question_id=qid, prompt=e["prompt"], kind=e["kind"],
            position=e["position"], answered=e["answered"],
            yes=e["yes"] if e["kind"] == "bool" else None,
            mean=mean, option_counts=option_counts,
        ))
    return sorted(out, key=lambda r: r.position)


def subject_rollups(db: Session, run: CampaignRun, campaign: Campaign) -> list[SubjectRollup]:
    """Per-subject breakdown — the unit a manager acts on.

    A run covers every truck, so a run-wide average across twelve of them is a
    number nobody can do anything with.
    """
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment

    rows = db.execute(
        select(
            CampaignResponse.subject_id,
            Employee.name,
            Truck.name,
            func.count(CampaignResponse.id),
        )
        .join(Employee, Employee.id == CampaignResponse.subject_id)
        .outerjoin(TruckAssignment,
                   TruckAssignment.id == CampaignResponse.truck_assignment_id)
        .outerjoin(Truck, Truck.id == TruckAssignment.truck_id)
        .where(
            CampaignResponse.run_id == run.id,
            CampaignResponse.company_id == run.company_id,
            Employee.company_id == run.company_id,
        )
        .group_by(CampaignResponse.subject_id, Employee.name, Truck.name)
    ).all()

    expected = _expected_per_subject(db, run, campaign)
    return [
        SubjectRollup(
            subject_id=sid, subject_name=name, truck_name=truck,
            expected=expected.get(sid, responded), responded=responded,
        )
        for sid, name, truck, responded in rows
    ]


def _expected_per_subject(db: Session, run: CampaignRun, campaign: Campaign) -> dict[UUID, int]:
    """How many people SHOULD have answered about each subject.

    Derived from the scoping invariant, so it already excludes the subject
    themselves and pre-boundary transfers (D3/D4). Computing it any other way
    would give a denominator that disagrees with who was actually asked.
    """
    from app.services.campaign_scope import subjects_for

    counts: dict[UUID, int] = {}
    for respondent_id in respondents_for(db, run, campaign):
        for elig in subjects_for(db, run, campaign, respondent_id):
            counts[elig.subject_id] = counts.get(elig.subject_id, 0) + 1
    return counts


def response_rate(db: Session, run: CampaignRun, campaign: Campaign) -> tuple[int, int]:
    """(responded, expected) — both numbers, never just a percentage.

    `17 / 23` tells a manager whether to chase; `74%` does not.
    """
    responded = db.execute(
        select(func.count(func.distinct(CampaignResponse.respondent_id)))
        .where(CampaignResponse.run_id == run.id,
               CampaignResponse.company_id == run.company_id)
    ).scalar() or 0
    # The run recorded this at open, so a crew change afterwards cannot move
    # the denominator under a number somebody already read.
    return responded, run.notified_count


def free_text(db: Session, run: CampaignRun) -> list[tuple[str, str]]:
    """(prompt, text) for every free-text answer, newest first, UNATTRIBUTED.

    No respondent_id in the SELECT (D13). The ordering is by the answer's own
    id rather than a timestamp it does not carry; within one run that is close
    enough to newest-first and does not require joining the response back in,
    which is where a respondent id would re-enter the query.
    """
    rows = db.execute(
        _answers_for_run(db, run)
        .where(CampaignAnswer.text_value.isnot(None))
        .order_by(CampaignAnswer.id.desc())
    ).all()
    return [(prompt, text) for _qid, prompt, _k, _p, _b, _i, text in rows]


def non_respondents(db: Session, run: CampaignRun, campaign: Campaign) -> list[tuple[UUID, str]]:
    """Who was asked and has not answered, BY NAME.

    Deliberately not anonymous, and the one place here that names anybody.
    Chasing a missing response requires knowing who to chase, and "did not
    answer" is not an opinion about a colleague — it carries no answer content,
    so D13's attribution gate does not apply.
    """
    asked = set(respondents_for(db, run, campaign))
    answered = {
        r[0] for r in db.execute(
            select(CampaignResponse.respondent_id)
            .where(CampaignResponse.run_id == run.id,
                   CampaignResponse.company_id == run.company_id)
        ).all()
    }
    missing = asked - answered
    if not missing:
        return []
    rows = db.execute(
        select(Employee.id, Employee.name)
        .where(Employee.id.in_(missing), Employee.company_id == run.company_id)
        .order_by(Employee.name.asc())
    ).all()
    return [(i, n) for i, n in rows]


class TrendPoint(NamedTuple):
    run_id: UUID
    date: str
    responded: int
    expected: int
    # question_id -> rate (0..1) for bool, mean for scale. None below the
    # minimum-N gate.
    per_question: dict[UUID, float | None]


def campaign_trend(db: Session, campaign: Campaign, limit: int = 26) -> list[TrendPoint]:
    """Across runs of one campaign — "is this getting better?"

    A retired question simply stops appearing once no run contains it, rather
    than continuing under a new wording: answers point at the question row they
    were collected against (D2 supersession), so the series ends where the
    question was retired.
    """
    runs = db.execute(
        select(CampaignRun)
        .where(CampaignRun.campaign_id == campaign.id,
               CampaignRun.company_id == campaign.company_id)
        .order_by(CampaignRun.date.desc())
        .limit(limit)
    ).scalars().all()

    points: list[TrendPoint] = []
    for run in reversed(runs):
        per_q: dict[UUID, float | None] = {}
        for roll in question_rollups(db, run):
            if roll.answered < MIN_RESPONSES_FOR_A_RATE:
                # Show the count, not a rate. ADR-473: a metric from two
                # responses reads as a judgement and is noise.
                per_q[roll.question_id] = None
            elif roll.kind == "bool" and roll.yes is not None:
                per_q[roll.question_id] = round(roll.yes / roll.answered, 3)
            elif roll.kind == "scale":
                per_q[roll.question_id] = roll.mean
        responded = db.execute(
            select(func.count(func.distinct(CampaignResponse.respondent_id)))
            .where(CampaignResponse.run_id == run.id,
                   CampaignResponse.company_id == run.company_id)
        ).scalar() or 0
        points.append(TrendPoint(
            run_id=run.id, date=run.date.isoformat(),
            responded=responded, expected=run.notified_count,
            per_question=per_q,
        ))
    return points
