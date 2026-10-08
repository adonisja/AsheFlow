"""Unlocking who said what, by approved request (ADR-485 D13).

Campaign answers are anonymous by default. `campaign_responses.respondent_id`
exists — a double-submit guard and "have I answered?" are impossible without
it — but nothing reads it across users, and no endpoint returns it.

WHY A REQUEST AND NOT A TOGGLE
==============================

A self-serve reveal is anonymity in name only. A manager who can click through
whenever they like is a manager respondents must assume is reading their name,
and a survey people answer carefully is one they believe is anonymous.

So the unlock is a request to an ADMIN:

    manager asks  ->  admin approves  ->  the run is attributed, for a window
                      (never their own request)

Four constraints, each doing real work:

  * **One run, never a campaign.** A standing grant over a campaign is the
    self-serve reveal with extra steps.
  * **A reason of at least ten words.** The smallest bar that makes "following
    up" impossible to type. It is free text and carries every D14 constraint.
  * **Only an admin approves, never their own request.** A manager asks; an
    admin decides. Both ids land in the audit, so "who saw this, and who let
    them" has one answer.
  * **Approval expires.** A grant that never closes is a permission, not an
    exception.

APPROVAL AND USE ARE SEPARATE FACTS
===================================

Reading an attributed run writes its own audit entry. An approval nobody acted
on and an approval read eleven times are different events, and only the audit
can tell them apart.

WHAT THIS NEVER UNLOCKS
=======================

D5 is unconditional and this does not weaken it: the SUBJECT never sees
responses about them, approved or not. Attribution raises the ceiling for
management, not for the person being reviewed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.campaign import AttributionRequest, CampaignResponse, CampaignRun
from app.models.employee import Employee
from app.services.audit import write_audit

# How long an approval lasts. Short and FIXED rather than configurable: a
# tenant-tunable window would be set to a year by the first operator who found
# the re-request annoying, and the point of the expiry is that re-asking is
# cheap while standing access is not.
APPROVAL_WINDOW = timedelta(hours=48)

# "Following up" is three words. Ten is the smallest bar that forces an actual
# sentence about an actual situation.
MIN_REASON_WORDS = 10


class AttributionError(RuntimeError):
    """A refusal the caller should turn into a specific HTTP status.

    `status` is carried so the router does not re-derive it from the message —
    the reason a request is refused decides whether the caller can fix it.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def reason_word_count(reason: str) -> int:
    return len([w for w in (reason or "").split() if w.strip()])


def request_attribution(
    db: Session, run: CampaignRun, requester: Employee, reason: str,
) -> AttributionRequest:
    """A manager asks to see who said what on ONE run.

    Does not grant anything. The request is a record that someone asked, which
    is itself worth having even when the answer is no.
    """
    if reason_word_count(reason) < MIN_REASON_WORDS:
        raise AttributionError(
            422,
            f"Give a reason of at least {MIN_REASON_WORDS} words describing why "
            f"this specific run needs to be attributed.",
        )

    # A second pending request for the same run by the same person is not a
    # second request, it is impatience.
    existing = db.execute(
        select(AttributionRequest).where(
            AttributionRequest.run_id == run.id,
            AttributionRequest.company_id == run.company_id,
            AttributionRequest.requested_by == requester.id,
            AttributionRequest.approved_at.is_(None),
            AttributionRequest.denied_at.is_(None),
        )
    ).scalars().first()
    if existing is not None:
        raise AttributionError(409, "You already have a request pending on this run.")

    req = AttributionRequest(
        company_id=run.company_id,
        run_id=run.id,
        requested_by=requester.id,
        reason=reason.strip(),
    )
    db.add(req)
    db.flush()
    write_audit(
        db=db,
        company_id=str(run.company_id),
        actor_id=str(requester.id),
        action_type="campaign.attribution_requested",
        target_table="campaign_runs",
        target_id=str(run.id),
        after={"request_id": str(req.id), "reason": req.reason},
    )
    return req


def approve(db: Session, req: AttributionRequest, approver: Employee) -> AttributionRequest:
    """An admin grants the request, for a bounded window.

    The caller is responsible for the role gate; this enforces the rules a gate
    cannot express.
    """
    # One-way stamps, 409-guarded (ADR-115 D2).
    if req.approved_at is not None:
        raise AttributionError(409, "This request was already approved.")
    if req.denied_at is not None:
        raise AttributionError(409, "This request was already denied.")

    # Never your own. An admin who can approve their own request is a
    # single-party unlock with two columns.
    if req.requested_by == approver.id:
        raise AttributionError(
            403, "Someone else has to approve a request you made.")

    now = datetime.now(timezone.utc)
    req.approved_by = approver.id
    req.approved_at = now
    req.expires_at = now + APPROVAL_WINDOW
    db.flush()

    write_audit(
        db=db,
        company_id=str(req.company_id),
        actor_id=str(approver.id),
        action_type="campaign.attribution_approved",
        target_table="campaign_runs",
        target_id=str(req.run_id),
        # Both ids and the stated reason, so "who saw this, and who let them"
        # has one answer without joining three tables.
        after={"request_id": str(req.id),
               "requested_by": str(req.requested_by),
               "reason": req.reason,
               "expires_at": req.expires_at.isoformat()},
    )
    return req


def deny(db: Session, req: AttributionRequest, approver: Employee) -> AttributionRequest:
    """Refuse the request. Audited as deliberately as an approval.

    A denial that leaves no trace makes "nobody asked" and "somebody asked and
    was told no" look identical later.
    """
    if req.approved_at is not None:
        raise AttributionError(409, "This request was already approved.")
    if req.denied_at is not None:
        raise AttributionError(409, "This request was already denied.")

    req.denied_at = datetime.now(timezone.utc)
    req.approved_by = approver.id   # who decided, not who granted
    db.flush()
    write_audit(
        db=db,
        company_id=str(req.company_id),
        actor_id=str(approver.id),
        action_type="campaign.attribution_denied",
        target_table="campaign_runs",
        target_id=str(req.run_id),
        after={"request_id": str(req.id), "requested_by": str(req.requested_by)},
    )
    return req


def active_grant(
    db: Session, run: CampaignRun, viewer: Employee,
) -> AttributionRequest | None:
    """The viewer's live grant on this run, or None.

    Checked at READ time, every time. An approval that has expired is not a
    grant, and a grant belonging to a different manager is not this viewer's.
    """
    now = datetime.now(timezone.utc)
    return db.execute(
        select(AttributionRequest).where(
            AttributionRequest.run_id == run.id,
            AttributionRequest.company_id == run.company_id,
            AttributionRequest.requested_by == viewer.id,
            AttributionRequest.approved_at.isnot(None),
            AttributionRequest.denied_at.is_(None),
            AttributionRequest.expires_at > now,
        )
    ).scalars().first()


def attributed_responses(
    db: Session, run: CampaignRun, viewer: Employee,
) -> list[tuple[UUID, str, UUID]]:
    """(response_id, respondent_name, respondent_id) for an unlocked run.

    Raises unless the viewer holds a live grant. This is the ONLY function in
    the codebase that returns a campaign respondent's identity, which is why
    the check lives here rather than in a router that might be copied.

    Writing the audit row is part of reading: approval and use are separate
    facts, and an approval nobody acted on and one read eleven times must not
    look the same.
    """
    grant = active_grant(db, run, viewer)
    if grant is None:
        raise AttributionError(
            403,
            "Responses on this run are anonymous. An admin can approve an "
            "attribution request if there is a documented reason.",
        )

    rows = db.execute(
        select(CampaignResponse.id, Employee.name, CampaignResponse.respondent_id)
        .join(Employee, Employee.id == CampaignResponse.respondent_id)
        .where(CampaignResponse.run_id == run.id,
               CampaignResponse.company_id == run.company_id,
               Employee.company_id == run.company_id)
        .order_by(Employee.name.asc())
    ).all()

    write_audit(
        db=db,
        company_id=str(run.company_id),
        actor_id=str(viewer.id),
        action_type="campaign.attribution_viewed",
        target_table="campaign_runs",
        target_id=str(run.id),
        after={"request_id": str(grant.id), "responses": len(rows)},
    )
    return [(rid, name, resp_id) for rid, name, resp_id in rows]
