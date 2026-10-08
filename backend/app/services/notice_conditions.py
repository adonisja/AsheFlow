"""Who a due notice actually reaches, and whether it fires at all (ADR-488 D5).

THE CONDITION DECIDES THE AUDIENCE
==================================

Not two separate questions. `DRIVER_MISSING_FUEL_LOG` returns the drivers who
have not filed, which is both the firing test (empty => do not fire) and the
recipient list. That is what makes ADR-487 D2's "name the trucks" fix and this
migration the same change: the condition returns rows, and the message
interpolates them.

The alternative -- a boolean condition plus a separate audience query -- was
rejected because `alert_finalization_deadline` is the cautionary example. It
tested `.first()` for "does ANY assignment exist today", which is why it could
not name the trucks AND why it fired at a dispatcher who finalised everything at
08:00. One query that returns the affected rows cannot have that defect.

A CLOSED ENUM, NOT AN EXPRESSION
================================

A tenant-expressible condition is a query language, and a query language against
tenant data reached from a scheduler is a surface this system has no reason to
open. A tenant authoring a notice gets ALWAYS; the rest read data only the
platform's own code understands.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notice import Condition

logger = logging.getLogger(__name__)


def resolve_recipients(
    db: Session,
    company_id,
    notice,
    local_today: date,
) -> tuple[list, dict]:
    """(recipients, context) for a due notice. An empty list means "do not fire".

    `context` carries whatever the body may interpolate — currently the truck
    names for the unfinalized-dispatch notice, which is the "name the trucks"
    fix ADR-487 D2 identified and deferred.
    """
    cond = notice.condition

    if cond == Condition.ALWAYS:
        return _by_audience(db, company_id, notice.audience), {}

    if cond == Condition.UNFINALIZED_DISPATCH_EXISTS:
        return _unfinalized_dispatch(db, company_id, notice, local_today)

    if cond == Condition.DRIVER_MISSING_FUEL_LOG:
        return _drivers_missing_fuel_log(db, company_id, local_today), {}

    if cond == Condition.MFA_DEADLINE_WITHIN_WARNING:
        return _mfa_deadline_approaching(db, company_id), {}

    logger.error("notice %s has unknown condition %r", notice.id, cond)
    return [], {}


def _by_audience(db: Session, company_id, audience: str) -> list:
    """Active employees in one role, or all of them.

    Dimension 1: scoped by company_id. Without it, one tenant's notice reaches
    every tenant's employees in that role.
    """
    q = db.query(Employee).filter(
        Employee.company_id == company_id,
        Employee.is_active.is_(True),
    )
    if audience != "all":
        q = q.filter(Employee.role == audience)
    return q.all()


def _unfinalized_dispatch(db: Session, company_id, notice, local_today: date):
    """Dispatch, plus the names of the trucks that are not finalized.

    `status != "completed"` is the marker `finalize_dispatch` sets — the same
    one ADR-487 D2 used when it fixed this query in the old task. Joining Truck
    for the names is what lets the body say WHICH trucks, and both sides of the
    join are company-scoped: a join adds a second table, and filtering one side
    does not scope the other.
    """
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment

    rows = (
        db.query(Truck.name)
        .join(TruckAssignment, TruckAssignment.truck_id == Truck.id)
        .filter(
            TruckAssignment.company_id == company_id,
            Truck.company_id == company_id,
            TruckAssignment.date == local_today,
            TruckAssignment.status != "completed",
        )
        .all()
    )
    names = [r[0] for r in rows]
    if not names:
        # The tenant finalised everything. The old task fired anyway, which is
        # what made it a nag (ADR-487 D2, defect 4).
        return [], {}

    # Capped at 8 plus a count: a station with thirty outstanding trucks needs a
    # number, not thirty names in a notification body.
    shown = names[:8]
    suffix = f" and {len(names) - 8} more" if len(names) > 8 else ""
    noun = "truck" if len(names) == 1 else "trucks"
    return (
        _by_audience(db, company_id, notice.audience),
        {"trucks": ", ".join(shown) + suffix, "count": len(names), "noun": noun},
    )


def _drivers_missing_fuel_log(db: Session, company_id, local_today: date) -> list:
    """Drivers dispatched and checked in today with no FuelMileageLog.

    The same three conditions `remind_fuel_log_missing` tests, in one query
    instead of three set-differences in Python. Checked-in matters: a driver who
    never arrived has nothing to file.
    """
    from app.models.assignment_member import AssignmentMember
    from app.models.field_ops import CheckIn, FuelMileageLog
    from app.models.truck_assignment import TruckAssignment

    dispatched = (
        db.query(AssignmentMember.employee_id)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == local_today,
            AssignmentMember.role == "driver",
        )
        .subquery()
    )
    checked_in = (
        db.query(CheckIn.employee_id)
        .filter(CheckIn.company_id == company_id, CheckIn.date == local_today)
        .subquery()
    )
    # `driver_id`, NOT `employee_id`. The column is spelled differently on this
    # model than on CheckIn and AssignmentMember, and `FuelMileageLog.employee_id`
    # is well-shaped, plausible, and an AttributeError at REQUEST time rather
    # than at import — Dimension 3's exact failure shape, caught by checking the
    # class rather than trusting the pattern of its siblings.
    filed = (
        db.query(FuelMileageLog.driver_id)
        .filter(
            FuelMileageLog.company_id == company_id,
            FuelMileageLog.date == local_today,
        )
        .subquery()
    )
    return (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.is_active.is_(True),
            Employee.id.in_(db.query(dispatched.c.employee_id)),
            Employee.id.in_(db.query(checked_in.c.employee_id)),
            Employee.id.notin_(db.query(filed.c.driver_id)),
        )
        .all()
    )


def _mfa_deadline_approaching(db: Session, company_id) -> list:
    """Employees whose MFA grace period ends within a warning band.

    The window arithmetic is LIFTED from `warn_before_mfa_deadline` rather than
    re-derived, including two things a rewrite would have got wrong:

    1. The grace length is `mfa_status.DEFAULT_MFA_GRACE_DAYS`, a platform
       constant — NOT a CompanyConfig column. A first draft of this function
       invented `cfg.mfa_grace_days`, which exists on no class; it would have
       silently fallen back to a hardcoded 14 via `getattr(..., None) or 14` and
       been wrong the day the platform constant changed.

    2. **Privileged roles have no grace at all** (ADR-377). Their path is
       ADR-465's wall from the first sign-in, not a countdown, so warning them
       about a deadline they do not have is both wrong and confusing. The role
       filter is what encodes that, and it is the kind of rule that only exists
       in the original.

    Derived entirely from a column — no Cognito call — so the SQL narrows to the
    handful of rows inside the band before anything else runs. A clock that
    never started is excluded by the NOT NULL term rather than evaluated and
    discarded.
    """
    from app.services import mfa_status
    from app.tasks.mfa_deadline_warnings import BANDS

    now = datetime.now(timezone.utc)
    grace = mfa_status.DEFAULT_MFA_GRACE_DAYS
    # BANDS is a DICT ({3: "mfa_deadline_3d", 1: "mfa_deadline_1d"}), so max()
    # and `in` operate on its KEYS — the days-remaining thresholds. Spelled out
    # because `max(BANDS)` reads like a set/list operation and would silently
    # mean something else if BANDS ever became a list of (days, type) pairs.
    widest = max(BANDS.keys())
    window_opens = now - timedelta(days=grace - widest)
    deadline_at = now - timedelta(days=grace)

    candidates = (
        db.query(Employee)
        .filter(
            # Dimension 1. The old task had no company filter because it ran
            # once for every tenant at the same server hour; a per-tenant notice
            # must scope, or one tenant's sweep warns another's employees.
            Employee.company_id == company_id,
            Employee.is_active.is_(True),
            Employee.mfa_grace_started_at.isnot(None),
            Employee.mfa_grace_started_at <= window_opens,
            # Not already past the deadline: someone past it is blocked NOW and
            # looking at the wall. A notice telling them to act "soon" would be
            # both late and wrong.
            Employee.mfa_grace_started_at > deadline_at,
        )
        .all()
    )

    out = []
    for emp in candidates:
        # Role, not Cognito groups: this path has no token to read groups from.
        if mfa_status.tier_for(emp.role, {emp.role}) != "field":
            continue        # ADR-377: no grace, so no countdown
        started = emp.mfa_grace_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        remaining = (started + timedelta(days=grace) - now).days
        if remaining in BANDS.keys():
            out.append(emp)
    return out
