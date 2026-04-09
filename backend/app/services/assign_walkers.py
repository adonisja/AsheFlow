import random
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.employee_relationship import EmployeeRelationship
from app.services.calculate_weights import calculate_weights
from app.services.ban_override import check_ban_override
from app.services.constants import MIN_WALKERS_PER_TRUCK

def assign_walkers(
    available_walkers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session
) -> list:
    """Assign walkers to trucks with ban enforcement, override logic, and per-truck caps.

    Processes ban relationships from all existing crew members.  Walker-to-walker
    bans may be overridden via ``check_ban_override`` when the candidate is
    preferred by a driver or trainer.  Falls back to uniform weights when all
    trucks are banned.  Mutates ``assigned_crews`` in place.

    Args:
        available_walkers: List of Walker Employee ORM objects to assign.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        base_weights: Dict mapping truck_id to its base selection weight.
        db: Database session.

    Returns:
        A list of warning dicts for walkers who could not avoid all bans,
        each with keys ``"employee_id"`` and ``"banned_by"``.
    """
    # copy so we can iterate without mutating the caller's list
    remaining_walkers = available_walkers.copy()
    warnings = []

    # index walkers by id so we can fetch the ORM object during ban-override checks
    walker_obj_by_id = {w.id: w for w in remaining_walkers}

    # covers all currently assigned roles (driver + trainer + already-placed walkers)
    crew_to_truck = {
        c["id"]: truck_id for truck_id, crew in assigned_crews.items()
        for c in crew
    }

    # separate index just for walkers — used to distinguish walker-vs-walker bans,
    # which are eligible for override, from driver/trainer bans, which are not
    walker_to_truck = {
        c["id"]: truck_id for truck_id, crew in assigned_crews.items()
        for c in crew if c["role"] == "walker"
    }

    # single query covering the full crew — trainers and drivers are already placed,
    # so their bans must be respected before we process walkers
    ban_records = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            or_(
                EmployeeRelationship.employee_id.in_(crew_to_truck.keys()),
                EmployeeRelationship.target_employee_id.in_(crew_to_truck.keys())
            )
        ).all()
    )

    # pre-build map of walker_id → [(truck_id, banner_id, is_walker), ...]
    # storing is_walker so we can decide override eligibility without re-querying
    banned_trucks_by_walker = {}
    for ban in ban_records:
        if ban.employee_id in crew_to_truck:
            truck_id = crew_to_truck[ban.employee_id]
            is_walker = ban.employee_id in walker_to_truck
            banned_trucks_by_walker.setdefault(ban.target_employee_id, []).append(
                (truck_id, ban.employee_id, is_walker)
            )
        else:
            truck_id = crew_to_truck[ban.target_employee_id]
            is_walker = ban.target_employee_id in walker_to_truck
            banned_trucks_by_walker.setdefault(ban.employee_id, []).append(
                (truck_id, ban.target_employee_id, is_walker)
            )

    for walker in remaining_walkers:
        raw_bans = banned_trucks_by_walker.get(walker.id, [])
        banned_truck_ids = []

        for truck_id, banner_id, is_walker in raw_bans:
            if not is_walker:
                # driver/trainer bans are absolute — the walker cannot go to this truck
                banned_truck_ids.append(truck_id)
                continue
            offending_walker = walker_obj_by_id.get(banner_id)
            if not offending_walker:
                # banner was already placed and isn't in the unassigned pool; treat ban as hard
                banned_truck_ids.append(truck_id)
                continue
            # walker-vs-walker ban: check if the truck's senior crew (driver/trainer)
            # prefers the candidate over the offending walker — if so, swap them out
            overridden = check_ban_override(
                walker.id, offending_walker, truck_id, assigned_crews, base_weights, banned_truck_ids, db
            )
            if not overridden:
                banned_truck_ids.append(truck_id)

        # recount per iteration because earlier walkers in this loop already changed crews
        walker_counts = {
            truck_id: sum(1 for c in crew if c["role"] == "walker")
            for truck_id, crew in assigned_crews.items()
        }

        # enforce minimum spread before any truck can receive extra walkers
        first_pass_active = any(count < MIN_WALKERS_PER_TRUCK for count in walker_counts.values())
        capped_trucks = [
            truck_id for truck_id, count in walker_counts.items()
            if first_pass_active and count >= MIN_WALKERS_PER_TRUCK
        ]

        # add spread caps on top of ban exclusions
        banned_truck_ids += capped_trucks

        weights = calculate_weights(
            employee_id=walker.id,
            employee_role="walker",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=banned_truck_ids,
            db=db
        )

        truck_ids = list(weights.keys())
        truck_weights = list(weights.values())

        # all-zero means every truck is excluded — log a warning and fall back to uniform so dispatch still completes
        if all(w == 0 for w in truck_weights):
            banned_by = [banner_id for _, banner_id, _ in raw_bans]
            warnings.append({"employee_id": walker.id, "banned_by": banned_by})
            truck_weights = [1] * len(truck_ids)

        selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
        assigned_crews[selected_truck].append({"id": walker.id, "role": "walker"})

    return warnings
