"""Route capability checks (ADR-212).

Single source of "who can do what on a route", replacing the scattered
``(route.assigned_to == caller.id OR route.paired_trainee_id == caller.id)``
checks that got the two sides of a paired route confused.

A route's membership is its RouteParticipant rows (lazy-joined onto the route):
exactly one ``executor`` (assignee-of-record — a walker, or the trainee in a
training pair) and zero-or-more ``supervisor`` (a trainer overseeing it).

Capability tiers (ADR-212 "either executes, trainer supervises"):
  - execute   : any participant (executor OR supervisor). Delivery actions —
                mark stop, back-at-truck, status updates.
  - supervise : a supervisor participant only. Authority actions — reassign,
                override, arrival-confirm / rebalance, approve Phase-4 opt-in.
  - read      : any participant, OR an oversight/crew role scoped to the truck.

These operate on the route's already-loaded participants; no DB round-trip.
Truck-scope checks for captain/oversight roles stay in the router (they need the
Session) — pass ``scoped_ok=True`` when the caller has passed that gate.
"""
from app.models.walker_route import Route
from app.models.employee import Employee

_OVERSIGHT_ROLES = {"dispatch", "management", "admin"}
_CAPTAIN_FIELD_ROLES = {"trainer", "driver"}


def _participant_ids(route: Route) -> set:
    return {p.employee_id for p in route.participants}


def _supervisor_ids(route: Route) -> set:
    return {p.employee_id for p in route.participants if p.role == "supervisor"}


def can_execute(caller: Employee, route: Route) -> bool:
    """True if the caller may perform execution (delivery) actions on the route.

    Either the executor or a supervisor — a trainer can step in and act on the
    paired route alongside the trainee.
    """
    return caller.id in _participant_ids(route)


def can_supervise(caller: Employee, route: Route) -> bool:
    """True if the caller holds supervisory control over the route.

    Supervisor participants only (the trainer). Oversight roles
    (dispatch/management/admin) are handled by their own endpoint role gates —
    this function answers the *participant-level* supervisory question.
    """
    return caller.id in _supervisor_ids(route)


def can_read(caller: Employee, route: Route, *, scoped_ok: bool = False) -> bool:
    """True if the caller may read the route.

    - oversight roles: always.
    - captain/field roles (trainer/driver): when scoped to the route's truck
      (router verifies truck scope and passes scoped_ok=True).
    - anyone who is a participant.
    """
    if caller.role in _OVERSIGHT_ROLES:
        return True
    if caller.role in _CAPTAIN_FIELD_ROLES and scoped_ok:
        return True
    return caller.id in _participant_ids(route)
