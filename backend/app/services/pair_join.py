"""Shared D2 late-trainee join (ADR-199).

A trainee who is not already carried by a committed route JOINS the trainer's
existing route: stamp ``paired_trainee_id`` and lift ``capacity_limit_paired``
to the 1.5× value. No structural rework — no adjacent-tote absorption, no new
route. Used by:
  - walker_routes.arrival_confirm (trainee arrives after the sort)
  - dispatch.reassign_trainee_day_of (Phase B: trainer late/absent → dispatch
    repoints the trainee to a new trainer, then joins the new trainer's route)

Kept as a service (not a router helper) so neither proprietary router imports
the other. Does NOT commit — the caller owns the transaction (flush/audit/commit).
"""
from fastapi import HTTPException, status

from app.schemas.walker_routes import EFFORT_CAPACITY_PAIRED


def find_trainer_route(all_routes, trainer_id, trainee_id):
    """Return the trainer's route to join the trainee to, or None.

    Priority:
      1. a route already carrying this trainee (pre-sort seeded, ADR-145 path)
      2. the trainer's own route not yet paired (stamp the join now)
    """
    route = next(
        (r for r in all_routes
         if r.assigned_to == trainer_id and r.paired_trainee_id == trainee_id),
        None,
    )
    if route is None:
        route = next(
            (r for r in all_routes
             if r.assigned_to == trainer_id and r.paired_trainee_id is None),
            None,
        )
    return route


def join_trainee_to_route(all_routes, trainer_id, trainee_id):
    """Perform the D2 join and return (route, paired_cap).

    Raises 404 if the trainer has no route to join, 409 if that route already
    has ``capacity_limit_paired`` set (arrival already confirmed for a pair).
    Mutates the route in place; the caller flushes/commits.
    """
    route = find_trainer_route(all_routes, trainer_id, trainee_id)
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route assigned to the trainer to join the trainee to.",
        )
    if route.capacity_limit_paired is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Arrival already confirmed for this trainer/trainee pair. Paired capacity is already set.",
        )
    paired_cap = EFFORT_CAPACITY_PAIRED.get(route.effort_class, EFFORT_CAPACITY_PAIRED["standard"])
    route.paired_trainee_id = trainee_id
    route.capacity_limit_paired = paired_cap
    return route, paired_cap
