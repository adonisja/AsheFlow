"""Who may answer about whom, on a campaign run (ADR-485 D3/D4).

THE INVARIANT
=============

    A response is valid only if respondent and subject shared ONE assignment
    on the RUN's date.

Everything the user asked for falls out of that single statement:

  * **No cross-truck contamination.** Truck A's crew can never answer about
    Truck B's driver — there is no assignment containing both.
  * **No cross-date contamination.** Truck A's crew on 10/01 cannot answer a
    run issued for 09/30, because the assignment's date must equal the run's.
  * **No retroactive access.** Crew assigned on 09/30 never see a run issued
    for 10/01, for the same reason.
  * **Nobody reviews themselves** (`respondent != subject`).

ONE QUERY, TWO PROJECTIONS
==========================

"Who may I answer about" and "may I answer about THIS person" are the same
self-join with a different projection, deliberately. Two code paths that must
agree is how they stop agreeing: a list that offers a subject the submit path
then refuses is a bug the user sees, and a submit path laxer than the list is a
bug nobody sees.

The role is a BOUND PARAMETER, not a branch. Compiling with
`subject_role='driver'` and `'captain'` produces byte-identical SQL, so a third
subject role needs no new code (D16).

WHAT THIS DOES NOT DO
=====================

It does not read "today". Every date comes from the RUN, so a run opened late,
read late, or answered late still scopes to the day it was about.
"""
from __future__ import annotations

from datetime import timedelta
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.assignment_member import AssignmentMember
from app.models.campaign import Campaign, CampaignRun
from app.models.truck_assignment import TruckAssignment
from app.services.local_date import company_datetime, company_tz

# ADR-485 D4. A transfer BEFORE this boundary is an administrative reshuffle --
# a crew member asked to move and it was approved -- and they respond only about
# their final active assignment. AFTER it they genuinely worked under that
# subject and respond about both trucks.
#
# Not a new number: it is the same threshold `activate_survey` already uses to
# decide a survey may be sent at all. One boundary, one meaning.
TRANSFER_COUNTS_AFTER = timedelta(hours=3)


class Eligibility(NamedTuple):
    """One (subject, assignment) pair a respondent may answer about."""
    subject_id: UUID
    truck_assignment_id: UUID


def _transfer_cutoff(db: Session, run: CampaignRun):
    """The instant after which a transfer counts, or None if unknowable.

    Returns None when the company has no `shift_start` configured. The caller
    treats that as "cannot evaluate the transfer rule", and transferred members
    are then excluded rather than guessed at -- a response attributed to the
    wrong truck is worse than a response not collected.
    """
    from app.services.company_config import get_company_config  # local: avoids a cycle

    cfg = get_company_config(db, run.company_id)
    if cfg is None or cfg.shift_start is None:
        return None
    tz = company_tz(db, run.company_id)
    return company_datetime(tz, run.date, cfg.shift_start) + TRANSFER_COUNTS_AFTER


def _base_query(db: Session, run: CampaignRun, campaign: Campaign, respondent_id: UUID):
    """The invariant, as one self-join. Both public functions project from it.

    Returns (query, S) -- the SUBJECT alias comes back with the query because a
    caller narrowing on the subject must reuse THIS alias. Re-aliasing
    `aliased(AssignmentMember, name="s")` produces a second, entirely
    unconstrained `assignment_members` in the FROM clause: a cartesian join
    that would let a respondent answer about anyone in the company. Verified by
    compiling it -- the SQL reads `FROM assignment_members AS s,
    assignment_members AS s`, which is valid SQL and a silent authorisation
    hole.
    """
    R = aliased(AssignmentMember, name="r")   # the respondent's row
    S = aliased(AssignmentMember, name="s")   # the subject's row

    cutoff = _transfer_cutoff(db, run)
    if cutoff is None:
        # Unknowable boundary: only an active membership counts.
        respondent_membership = R.status == "active"
    else:
        respondent_membership = or_(
            R.status == "active",
            and_(R.status == "transferred", R.departed_at >= cutoff),
        )

    return (
        select(S.employee_id, TruckAssignment.id)
        .join(TruckAssignment, TruckAssignment.id == S.assignment_id)
        .join(R, R.assignment_id == S.assignment_id)   # SAME assignment — the rule
        .where(
            # The RUN's date, never "today".
            TruckAssignment.date == run.date,
            # ADR-115 D1: every table carries its own company_id predicate. The
            # join alone would already confine this, but "it is implied by the
            # join" is exactly the reasoning that produces a cross-tenant read
            # the next time someone edits the FROM clause.
            TruckAssignment.company_id == run.company_id,
            R.company_id == run.company_id,
            S.company_id == run.company_id,
            R.employee_id == respondent_id,
            # The subject must hold the campaign's slot. AssignmentMember.role is
            # the SLOT (ADR-256), not the job title -- so a captain-titled
            # employee slotted as a walker is a respondent here, not a subject.
            S.role == campaign.subject_role,
            # The subject's own membership must be real on the day; a departed
            # or transferred subject is still the person who held the slot.
            S.status.in_(("active", "departed", "transferred")),
            S.employee_id != R.employee_id,
            respondent_membership,
        )
    ), S


def subjects_for(
    db: Session, run: CampaignRun, campaign: Campaign, respondent_id: UUID,
) -> list[Eligibility]:
    """Everyone this respondent may answer about on this run.

    Normally one pair. Two when the respondent transferred after the boundary
    and so worked under two subjects (D4).
    """
    query, _ = _base_query(db, run, campaign, respondent_id)
    rows = db.execute(query).all()
    return [Eligibility(subject_id=s, truck_assignment_id=a) for s, a in rows]


def may_answer_about(
    db: Session, run: CampaignRun, campaign: Campaign,
    respondent_id: UUID, subject_id: UUID,
) -> Eligibility | None:
    """The submit-time check. None means refuse.

    The SAME query as `subjects_for`, narrowed. The client never asserts who it
    may review -- it names a subject and this decides.
    """
    # The alias from the builder, NOT a fresh one — see _base_query.
    query, S = _base_query(db, run, campaign, respondent_id)
    row = db.execute(query.where(S.employee_id == subject_id)).first()
    return Eligibility(subject_id=row[0], truck_assignment_id=row[1]) if row else None


def assignments_without_a_subject(
    db: Session, run: CampaignRun, campaign: Campaign,
) -> list[UUID]:
    """Assignments on the run's date with nobody in the subject role (D16).

    ADR-256's index guarantees AT MOST one captain per truck, not at least one,
    so a truck running without one is an ordinary state. Those crews are not
    asked -- which D3 already handles, because the self-join finds no subject.

    What needs recording is that they were SKIPPED: a response rate quietly
    computed over a smaller denominator reads as 17/17 and gets acted on as
    though every truck was covered.
    """
    has_subject = (
        select(AssignmentMember.assignment_id)
        .where(
            AssignmentMember.company_id == run.company_id,
            AssignmentMember.role == campaign.subject_role,
        )
        .scalar_subquery()
    )
    rows = db.execute(
        select(TruckAssignment.id).where(
            TruckAssignment.date == run.date,
            TruckAssignment.company_id == run.company_id,
            TruckAssignment.id.notin_(has_subject),
        )
    ).all()
    return [r[0] for r in rows]


def respondents_for(
    db: Session, run: CampaignRun, campaign: Campaign,
) -> list[UUID]:
    """Everyone who should be asked, for the whole run.

    The denominator of the response rate (D15), and the notification list at
    open. Derived from the same invariant rather than from a role gate: the old
    survey gated on `["trainer", "walker"]`, which excluded every driver from
    ever responding about anyone, and never excluded the subject from their own
    review.
    """
    R = aliased(AssignmentMember, name="r")
    S = aliased(AssignmentMember, name="s")

    cutoff = _transfer_cutoff(db, run)
    membership = (
        R.status == "active" if cutoff is None
        else or_(R.status == "active",
                 and_(R.status == "transferred", R.departed_at >= cutoff))
    )

    rows = db.execute(
        select(R.employee_id)
        .join(TruckAssignment, TruckAssignment.id == R.assignment_id)
        .join(S, S.assignment_id == R.assignment_id)
        .where(
            TruckAssignment.date == run.date,
            TruckAssignment.company_id == run.company_id,
            R.company_id == run.company_id,
            S.company_id == run.company_id,
            S.role == campaign.subject_role,
            S.employee_id != R.employee_id,
            membership,
        )
        .distinct()
    ).all()
    return [r[0] for r in rows]
