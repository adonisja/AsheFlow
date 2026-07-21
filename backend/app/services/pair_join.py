"""Shared D2 late-trainee join (ADR-199, reworked for ADR-212 joint ownership).

A trainee who is not already carried by a committed route JOINS the route they
execute: attach the trainer as a ``supervisor`` RouteParticipant and lift
``capacity_limit_paired`` to the 1.5× value. No structural rework — no adjacent-
tote absorption, no new route. Used by:
  - walker_routes.arrival_confirm (trainee arrives after the sort)
  - dispatch.reassign_trainee_day_of (Phase B: trainer late/absent → dispatch
    repoints the trainee to a new trainer, then joins the new trainer's route)

ADR-212: the paired route is the TRAINEE's route (the trainee is the executor /
assignee-of-record). The old model looked the route up by the trainer's
``assigned_to`` — which never matched, because the trainer never owned it. Now
we find the route by its executor (the trainee) and add the trainer as a
supervisor participant.

Kept as a service (not a router helper) so neither proprietary router imports
the other. Does NOT commit — the caller owns the transaction (flush/audit/commit).
"""
import uuid

from fastapi import HTTPException, status

from app.models.walker_route import RouteParticipant
from app.schemas.walker_routes import EFFORT_CAPACITY_PAIRED


def find_executor_route(all_routes, trainee_id):
    """Return the route the trainee executes, or None.

    The trainee is the executor (assignee-of-record) of the paired route. A
    route is "the trainee's" when it has an ``executor`` participant whose
    employee_id is the trainee.
    """
    return next(
        (r for r in all_routes
         if any(p.role == "executor" and p.employee_id == trainee_id
                for p in r.participants)),
        None,
    )


def join_trainee_to_route(all_routes, trainer_id, trainee_id, company_id):
    """Perform the D2 join and return (route, paired_cap).

    Finds the trainee's (executor) route, attaches ``trainer_id`` as a
    ``supervisor`` participant if not already present, and lifts
    ``capacity_limit_paired`` to the 1.5× value.

    Raises 404 if the trainee has no route to join, 409 if that route already
    has ``capacity_limit_paired`` set (arrival already confirmed for a pair).
    Mutates the route in place (appends a participant); the caller flushes/commits.
    """
    route = find_executor_route(all_routes, trainee_id)
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route found for the trainee to join a trainer to.",
        )
    if route.capacity_limit_paired is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Arrival already confirmed for this trainer/trainee pair. Paired capacity is already set.",
        )

    # Attach the trainer as a supervisor participant (idempotent — skip if already
    # present so a re-run doesn't violate the (route_id, employee_id) unique key).
    already = any(
        p.role == "supervisor" and p.employee_id == trainer_id
        for p in route.participants
    )
    if not already:
        route.participants.append(
            RouteParticipant(
                id=uuid.uuid4(),
                company_id=company_id,
                employee_id=trainer_id,
                role="supervisor",
            )
        )

    paired_cap = EFFORT_CAPACITY_PAIRED.get(route.effort_class, EFFORT_CAPACITY_PAIRED["standard"])
    route.capacity_limit_paired = paired_cap
    return route, paired_cap
