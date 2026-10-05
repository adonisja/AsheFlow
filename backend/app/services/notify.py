"""The only way to raise a notification (ADR-487 D2).

WHY A HELPER AND NOT 83 CALL SITES
==================================

Routing a notification needs five things the call site does not have: the
severity, the channel set, the label, the tone and the icon. Those live in
`notification_spec.SPEC` (D1), and a registry that each site must remember to
consult is a registry that will be 90% applied forever — with the missing 10%
being the sites nobody revisited, which is where the injury alerts are.

So the lookup is not optional. `Notification.__init__` refuses direct
construction, and this module is the only caller that satisfies it.

WHY THE CONSTRUCTOR AND NOT A CI GREP
=====================================

A gate forbidding `db.add(Notification(` passes on
`db.add_all([Notification(...) for ...])` — which is literally the shape of
`walker_routes.py:1040`, the one site that turned out to have no `type=` at all.
The LEARNING_GUIDE already records this: "grepping for a function name misses its
wrappers". The constructor sees every path because every path goes through it.

Verified before relying on it: SQLAlchemy does NOT call `__init__` when
materialising a loaded row, so the guard constrains construction only and no read
path is affected.

NOTHING IS SENT HERE
====================

These functions only touch the session. The sends happen after the transaction
commits (D3), because ADR-324 found both halves of getting this wrong: a Discord
call placed before the commit took out the in-app notifications downstream of it,
and an alert committed with the main transaction was discarded when an unrelated
helper called `db.rollback()` in between.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification
from app.services.constants import (
    MANAGEMENT_ROLES,
    OVERSIGHT_ROLES,
    STATION_RESOLVE_ROLES,
)
from app.services.notification_spec import Spec, is_raisable, resolve_spec


class Audience:
    """Named recipient sets, each pointing at a constant that already exists.

    These are NOT new sets. `constants.py` already distinguishes them, and the
    distinctions are load-bearing:

      OVERSIGHT       includes `field_supervisor`, and `deps._PRIVILEGED_ROLES`
                      derives from it — so it is also an ownership bypass in
                      `assert_can_access`. The widest of the three.
      STATION_RESOLVE excludes `field_supervisor` deliberately: ADR-256 D12 keeps
                      them out because "they oversee the road, and ADR-016 settled
                      that an oversight role does not thereby acquire dispatch's
                      execution authority."
      MANAGEMENT      excludes dispatch. The payroll and offboarding notices use
                      this, and widening them would be a privacy change.

    Migrating a site means choosing which one it MEANT — a judgment call per
    site, not a mechanical substitution. The 12 sites that hand-wrote
    `["management", "admin"]` must not silently gain `dispatch` and
    `field_supervisor`.
    """

    OVERSIGHT = OVERSIGHT_ROLES                 # mgmt, admin, dispatch, field_supervisor
    STATION_RESOLVE = STATION_RESOLVE_ROLES     # dispatch, management, admin
    MANAGEMENT = MANAGEMENT_ROLES               # management, admin


def write_notification(
    db: Session,
    *,
    company_id: UUID | str,
    employee_id: UUID | str,
    type: str,
    message: str,
    dispatch_date: date | None = None,
    expires_at: datetime | None = None,
) -> Notification:
    """Raise one notification. The ONLY way to create one.

    Resolves SPEC[type] (D1) before the row exists, so an undeclared type fails
    at the call site rather than producing a row nothing can route. That also
    catches the `walker_routes.py:1040` class of defect — a construction with no
    `type=` at all — which currently adds rows that are silently discarded
    because `type` is NOT NULL and nothing commits them.

    Does not send. D3's after-commit hook does that.
    """
    spec = _resolve_raisable(type)
    notif = Notification(
        _via_helper=True,
        company_id=company_id,
        employee_id=employee_id,
        type=type,
        message=message,
        dispatch_date=dispatch_date,
        expires_at=expires_at,
    )
    db.add(notif)
    _record_intent(db, spec, notif)
    return notif


def fan_out(
    db: Session,
    *,
    company_id: UUID | str,
    audience: tuple[str, ...],
    type: str,
    message: str,
    dispatch_date: date | None = None,
    expires_at: datetime | None = None,
    exclude: set | None = None,
) -> list[Notification]:
    """Raise one notification per member of a named audience.

    51 of the 83 original sites were a `for` loop over a recipient query, each
    re-writing the `company_id` + `is_active` filter by hand. Three consequences
    of doing it once, here:

      * A misspelled role becomes unexpressible. Two sites filtered on
        `["admin", "manager"]` — the role is `management`, so those notifications
        reached admins only and nothing reported it.
      * The `is_active` filter cannot be forgotten. A notification addressed to a
        deactivated employee is a row nobody reads.
      * D3 gets ONE dispatch record for the batch rather than N, which is what
        makes "one Discord post per event" possible instead of one per recipient.

    `exclude` covers the real case of not double-notifying somebody who is both
    in the audience and the subject — `graduation_quiz.py` already does this by
    hand with a `trainer_already_notified` check.
    """
    spec = _resolve_raisable(type)
    recipients = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(list(audience)),
            Employee.is_active.is_(True),
        )
        .all()
    )
    skip = exclude or set()
    out: list[Notification] = []
    for emp in recipients:
        if emp.id in skip:
            continue
        notif = Notification(
            _via_helper=True,
            company_id=company_id,
            employee_id=emp.id,
            type=type,
            message=message,
            dispatch_date=dispatch_date,
            expires_at=expires_at,
        )
        db.add(notif)
        out.append(notif)

    if out:
        _record_intent(db, spec, *out)
    return out


def _resolve_raisable(notification_type: str) -> Spec:
    """SPEC lookup plus the retired check.

    A retired type still RESOLVES (so historical rows read) but must not be
    raised — D1's removal is two-step, and writing one would resurrect a type
    that was deliberately stopped.
    """
    spec = resolve_spec(notification_type)
    if not is_raisable(notification_type):
        raise ValueError(
            f"{notification_type!r} is RETIRED (ADR-487 D1) and must not be "
            f"raised. It still resolves so existing rows can be read. If this "
            f"type should come back, move it from RETIRED to SPEC deliberately."
        )
    return spec


def _record_intent(db: Session, spec: Spec, *notifications: Notification) -> None:
    """Record what to deliver, for the after-commit hook to pick up (D3).

    A no-op until D3 lands. Separated now so the migration does not have to be
    revisited: every site routed through this module is already recording its
    intent, and D3 only has to drain the list.
    """
    # D3: append Dispatch(spec.severity, spec.channels, notif.id) to a
    # session-scoped pending list, flushed on `after_commit`.
    return None
