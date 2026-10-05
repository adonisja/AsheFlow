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

import logging
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification
from app.services.constants import (
    MANAGEMENT_ROLES,
    OVERSIGHT_ROLES,
    STATION_RESOLVE_ROLES,
)
from app.services.notification_spec import (
    Channel,
    Severity,
    Spec,
    is_raisable,
    resolve_spec,
)

logger = logging.getLogger(__name__)

# Key under which a session's pending deliveries live. Namespaced because
# `session.info` is shared with anything else that wants per-session state.
_PENDING_KEY = "adr487_pending_notification_dispatches"


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

      ADMIN_ONLY      admins alone. The only member with no constant in
                      `constants.py`, because it is not an oversight set — it is
                      the audience for product feedback, which is a message to
                      whoever runs the tenant rather than to anyone operating
                      it. Kept narrow deliberately: a bug report is not dispatch
                      business.

    Migrating a site means choosing which one it MEANT — a judgment call per
    site, not a mechanical substitution. The 12 sites that hand-wrote
    `["management", "admin"]` must not silently gain `dispatch` and
    `field_supervisor`.
    """

    OVERSIGHT = OVERSIGHT_ROLES                 # mgmt, admin, dispatch, field_supervisor
    STATION_RESOLVE = STATION_RESOLVE_ROLES     # dispatch, management, admin
    MANAGEMENT = MANAGEMENT_ROLES               # management, admin
    ADMIN_ONLY = ("admin",)                     # admins alone — see below


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
    _require_tenant(type, company_id)
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
    _require_tenant(type, company_id)
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


def _require_tenant(notification_type: str, company_id) -> None:
    """A notification always belongs to a tenant. Platform-level is a DIFFERENT
    vocabulary, and the codebase already has it.

    `Notification.company_id` is NOT NULL because a notification addresses an
    EMPLOYEE, and an employee always belongs to a company. `PlatformAlert.
    company_id` is nullable, and NULL there MEANS "platform, not a tenant"
    (ADR-335, ADR-337 D4).

    ADR-324 D2 states the constraint that makes the two irreducible: "a
    super_admin has no Employee row, so Notification cannot address them at
    all." So a tenant-less notification is not a notification with a missing
    field — it is a platform alert wearing the wrong type.

    Refusing here rather than at the insert is the point. `feedback.py` reached
    the NOT NULL with `company_id=None` whenever a super admin (who has no
    employee row) submitted feedback: the admin query fanned out across EVERY
    tenant, and then every insert failed — a 500 raised after the feedback row
    had already been added. Caught while migrating the first file, with no test
    covering the path.
    """
    if company_id is None:
        raise ValueError(
            f"cannot raise {notification_type!r} with no company_id: a "
            f"Notification addresses an employee, and Notification.company_id "
            f"is NOT NULL (ADR-487 D2). For a platform-level condition with no "
            f"tenant, use services.integration_alerts.raise_platform_alert, "
            f"whose company_id is nullable and where NULL means 'platform' "
            f"(ADR-335). A super admin has no Employee row and cannot be "
            f"addressed by a Notification at all (ADR-324 D2)."
        )


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


# ── Delivery, after the transaction commits (ADR-487 D3) ─────────────────────
#
# These functions only touch the session. The sends happen on `after_commit`,
# because ADR-324 found BOTH halves of getting this wrong:
#
#   * a Discord call placed BEFORE the commit took out the in-app notifications
#     created downstream of it — "a dead secondary channel was taking out the
#     primary one";
#   * an alert committed WITH the main transaction was discarded when an
#     unrelated helper called db.rollback() in between.
#
# after_commit cannot send for a row that does not exist, and it cannot be
# skipped by a rollback. Both failures become unexpressible rather than fixed.


@dataclass(frozen=True)
class _Dispatch:
    """One row's delivery intent, recorded before the commit."""

    notification_id: str
    company_id: str
    employee_id: str
    type: str
    message: str
    severity: Severity
    channels: Channel


def _pending(session: Session) -> list[_Dispatch]:
    """The session's pending-delivery list.

    Stored in `session.info`, which SQLAlchemy provides for exactly this and
    which is discarded with the session — so a request that raises leaves no
    residue for the next one.
    """
    return session.info.setdefault(_PENDING_KEY, [])


def _record_intent(db: Session, spec: Spec, *notifications: Notification) -> None:
    """Record what to deliver. Sends nothing.

    Called with every row from one fan_out so the batch arrives as one unit —
    which is what makes "one Discord post per event" possible instead of one per
    recipient.
    """
    if not _deliverable(spec.channels):
        # A BANNER-only type is delivered by being read. Recording an intent
        # with nothing to do would mean sweeping rows that were never meant to
        # be dispatched, and the sweep's whole signal is "dispatched_at is NULL".
        return

    pending = _pending(db)
    for n in notifications:
        pending.append(_Dispatch(
            notification_id=str(n.id),
            company_id=str(n.company_id),
            employee_id=str(n.employee_id),
            type=n.type,
            message=n.message,
            severity=spec.severity,
            channels=spec.channels,
        ))


def _deliverable(channels: Channel) -> bool:
    """Does this channel set imply a SEND, as opposed to a render?

    BANNER, TICKER, GATE and PROMPT are all "the client shows it when it reads
    the row" — there is no server-side delivery. PUSH and DISCORD leave the
    building.
    """
    return bool(channels & (Channel.PUSH | Channel.DISCORD))


@event.listens_for(Session, "after_commit")
def _flush_notification_dispatches(session: Session) -> None:
    """Enqueue every recorded delivery, once the DB has accepted the rows.

    THREE PROPERTIES THIS RELIES ON, stated because nothing local demonstrated
    them before this (the only other SQLAlchemy listener in the repo is an
    Engine-level "connect" hook in one test):

    1. It fires OUTSIDE the transaction, after the commit succeeded. A send
       cannot be issued for a rolled-back row.
    2. It fires once per `Session.commit()`, for EVERY commit on that session —
       hence the clear() below. Without it, a request that commits twice
       re-sends the first commit's batch.
    3. It must not emit SQL. Writing here starts a new implicit transaction,
       which is why the payload carries what the task needs and the task
       re-reads anything else.

    Never raises. The rows are committed and the operation is complete; an
    enqueue failure is what the sweep exists to catch, and letting it propagate
    would turn a delivery problem into a 500 on an operation that succeeded.
    """
    pending = session.info.get(_PENDING_KEY)
    if not pending:
        return
    # Clear FIRST. If an enqueue raises, the next commit on this session must
    # not re-send the batch that partly went out.
    session.info[_PENDING_KEY] = []

    for d in pending:
        try:
            _enqueue(d)
        except Exception:
            logger.warning(
                "could not enqueue delivery for notification %s (type=%s) — the "
                "row is committed and the sweep will retry it",
                d.notification_id, d.type, exc_info=True,
            )


def _enqueue(d: _Dispatch) -> None:
    """Hand one delivery to Celery.

    PUSH is recorded and not yet sent: D5 builds the SNS path and the
    company-local quiet-hours hold. Logging the skip rather than silently
    dropping it means the gap is visible in the one place somebody would look.
    """
    if Channel.DISCORD in d.channels:
        from app.tasks.discord_delivery import send_discord

        send_discord.delay(
            "dm",
            {"employee_id": d.employee_id, "message": d.message},
            notification_id=d.notification_id,
            company_id=d.company_id,
        )

    if Channel.PUSH in d.channels:
        # D5. Not built: no device_tokens table, no SNS platform ARNs.
        logger.info(
            "push not yet wired for notification %s (type=%s, severity=%s) — "
            "ADR-487 D5",
            d.notification_id, d.type, d.severity.value,
        )
