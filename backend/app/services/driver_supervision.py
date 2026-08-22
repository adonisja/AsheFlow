"""ADR-264 D9 — who may supervise a driver trainee, in one place.

THE POINT OF THIS MODULE
------------------------
`field_supervisor` and `captain` are real roles that arrive in their own work.
When they do, "who can supervise a driver trainee" must change in exactly one
place. Every call site — dispatch pairing, the replacement suggester when a
supervisor declines, and manual assignment — goes through the predicate below.

**Never inline `role == "driver"` at a supervision check.** An inlined
comparison is precisely what makes threading a new role expensive later, and
this codebase has precedent for role lists drifting between call sites (the
`_allow_*` bundles in walker_routes.py, and ADR-211's consecutive-penalty bug,
which was a filter that had quietly stopped matching what its callers assumed).

WHY A DRIVER AND NOT A TRAINER
------------------------------
A walker `trainer` trains walkers. Drivers are trained by drivers: the trainee
drives and is the main worker for the day, and the supervisor assists from the
same truck (operator, 2026-08-07). A trainer has no vehicle or load-custody
authority to pass on, so the walker training role is not reusable here despite
the similar shape.
"""
from typing import Iterable

# The roles that may supervise a driver trainee for a day.
#
# `field_supervisor` and `captain` are deliberately ABSENT until those roles
# carry the operational authority this implies — ADR-264 D9 builds the seam, not
# the roles. Adding one here is the whole change; no call site needs editing.
SUPERVISING_ROLES: frozenset[str] = frozenset({"driver"})


def can_supervise_driver_trainee(employee) -> bool:
    """True when `employee` may supervise a driver trainee today.

    Deliberately takes the employee OBJECT rather than a role string: an
    inactive driver is not a candidate, and a caller passing `employee.role`
    alone would silently skip that check. Making the wider fact the argument
    makes the narrower mistake unavailable.
    """
    if employee is None:
        return False
    return bool(getattr(employee, "is_active", False)) and getattr(employee, "role", None) in SUPERVISING_ROLES


def eligible_supervisors(employees: Iterable) -> list:
    """The subset of `employees` that may supervise, order preserved.

    Used by the replacement suggester (D7) when a supervising driver declines.
    A list rather than a generator so callers can take len() without consuming
    it — the "no free supervisor" branch needs the count.
    """
    return [e for e in employees if can_supervise_driver_trainee(e)]
