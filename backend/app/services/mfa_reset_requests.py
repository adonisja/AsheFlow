"""Two-factor reset requests: who can act on them, and closing them (ADR-551).

A request is only a flag beside a reset button. It is created after the
requester proved the account's inbox (D2), shown to whoever can reset that
kind of account (D3), and closed by the reset itself (D4). Nothing here ever
changes the account's sign-in.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.mfa_reset_request import MfaResetRequest
from app.models.survey_register import SurveyContributor

logger = logging.getLogger(__name__)

#: D3: an unanswered request drops out of the lists; the person can ask again.
SHOWN_FOR = timedelta(days=7)
STAFF_GROUPS = frozenset({"super_admin", "platform_support"})
#: Who can reset a tenant employee (the /employees/{id}/mfa/reset gate).
TENANT_RESETTERS = ("admin", "management")


def classify(db: Session, sub: str, groups: set[str]) -> tuple[str, dict] | None:
    """("employee"|"surveyor"|"staff", identifying fields) or None.

    Employee first: a tenant account is reset by its own company, even if it
    also held a platform group by mistake. Then a live contributor row, then
    a staff group. Anything else has no one to ask.
    """
    emp = (db.query(Employee)
           .filter(Employee.cognito_sub == sub, Employee.is_active.is_(True)).first())
    if emp is not None:
        return "employee", {"company_id": emp.company_id, "employee": emp}
    c = (db.query(SurveyContributor)
         .filter(SurveyContributor.cognito_sub == sub, SurveyContributor.revoked_at.is_(None)).first())
    if c is not None and "surveyor" in groups:
        return "surveyor", {"contributor_id": c.id}
    if groups & STAFF_GROUPS:
        return "staff", {}
    return None


def record(db: Session, *, sub: str, kind: str, fields: dict, ip: str | None) -> tuple[MfaResetRequest, bool]:
    """The pending request for `sub`, creating it if there is none.

    Returns (request, created). One pending per account (D2): the partial
    unique index enforces it, and a concurrent duplicate is resolved by
    re-reading the winner rather than failing the person's request.
    """
    existing = (db.query(MfaResetRequest)
                .filter(MfaResetRequest.cognito_sub == sub, MfaResetRequest.status == "pending").first())
    if existing is not None:
        return existing, False
    req = MfaResetRequest(cognito_sub=sub, account_kind=kind, status="pending",
                          company_id=fields.get("company_id"),
                          contributor_id=fields.get("contributor_id"), request_ip=ip,
                          requested_at=datetime.now(timezone.utc))
    db.add(req)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = (db.query(MfaResetRequest)
                  .filter(MfaResetRequest.cognito_sub == sub, MfaResetRequest.status == "pending").one())
        return winner, False
    return req, True


def pending_since(db: Session, subs: list[str]) -> dict[str, datetime]:
    """{sub: requested_at} for pending requests inside the 7-day window."""
    if not subs:
        return {}
    cutoff = datetime.now(timezone.utc) - SHOWN_FOR
    rows = (db.query(MfaResetRequest.cognito_sub, MfaResetRequest.requested_at)
            .filter(MfaResetRequest.cognito_sub.in_(subs), MfaResetRequest.status == "pending",
                    MfaResetRequest.requested_at >= cutoff).all())
    return {sub: at for sub, at in rows}


def resolve_for(db: Session, sub: str, *, by_kind: str, by_ref: str | None) -> int:
    """D4: the reset closes the account's pending request. Caller commits."""
    n = 0
    for req in (db.query(MfaResetRequest)
                .filter(MfaResetRequest.cognito_sub == sub, MfaResetRequest.status == "pending").all()):
        req.status = "resolved"
        req.resolved_at = datetime.now(timezone.utc)
        req.resolved_by_kind = by_kind
        req.resolved_by_ref = (by_ref or "")[:64] or None
        n += 1
    return n
