import random
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.employee_relationship import EmployeeRelationship
from app.services.calculate_weights import calculate_weights
from app.services.ban_override import check_ban_override


def assign_walkers(
    available_walkers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session,
    extra_banned_truck_ids: list = None,
) -> list:
    """Assign walkers to trucks with guaranteed even distribution.

    Enforces a hard round-robin spread: a walker is only eligible for trucks
    currently at the minimum walker count.  Ban / fav / consecutive logic runs
    within that eligible set.  Walker-vs-walker bans may still be overridden
    via check_ban_override.  Only if every minimum truck is banned does the
    algorithm open up above-minimum trucks as a fallback.

    Args:
        available_walkers: List of Walker Employee ORM objects to assign.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        base_weights: Dict mapping truck_id to its base selection weight.
        db: Database session.
        extra_banned_truck_ids: Additional truck IDs to hard-ban for every
            walker in this call. Used by perform_walker_reassignment to prevent
            an evicted walker from being re-placed on the truck they were
            evicted from.

    Returns:
        A list of warning dicts for walkers who could not avoid all bans.
    """
    remaining_walkers = available_walkers.copy()
    warnings = []

    walker_obj_by_id = {w.id: w for w in remaining_walkers}

    # Full crew map (driver + trainer + already-placed walkers) for ban lookups.
    crew_to_truck = {
        c["id"]: truck_id
        for truck_id, crew in assigned_crews.items()
        for c in crew
    }

    walker_to_truck = {
        c["id"]: truck_id
        for truck_id, crew in assigned_crews.items()
        for c in crew if c["role"] == "walker"
    }

    ban_records = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            or_(
                EmployeeRelationship.employee_id.in_(crew_to_truck.keys()),
                EmployeeRelationship.target_employee_id.in_(crew_to_truck.keys()),
            ),
        )
        .all()
    ) if crew_to_truck else []

    # Pre-build banned-truck map with override eligibility flag.
    banned_trucks_by_walker: dict = {}
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
        # Resolve bans (with walker-vs-walker override logic).
        raw_bans = banned_trucks_by_walker.get(walker.id, [])
        hard_banned: list = list(extra_banned_truck_ids or [])

        for truck_id, banner_id, is_walker_ban in raw_bans:
            if not is_walker_ban:
                hard_banned.append(truck_id)
                continue
            offending_walker = walker_obj_by_id.get(banner_id)
            if not offending_walker:
                hard_banned.append(truck_id)
                continue
            overridden, reassigned_to = check_ban_override(
                walker.id, offending_walker, truck_id, assigned_crews, base_weights, hard_banned, db
            )
            if not overridden:
                hard_banned.append(truck_id)
            else:
                warnings.append({
                    "type": "ban_override_reassignment",
                    "evicted_employee_id": offending_walker.id,
                    "evicted_to_truck_id": reassigned_to,
                    "in_favour_of_employee_id": walker.id,
                    "from_truck_id": truck_id,
                })

        # Recount after every placement.
        walker_counts = {
            truck_id: sum(1 for c in crew if c["role"] == "walker")
            for truck_id, crew in assigned_crews.items()
        }

        min_count = min(walker_counts.values()) if walker_counts else 0
        min_trucks = [t for t, cnt in walker_counts.items() if cnt == min_count]

        # Eligible = minimum-count trucks that aren't hard-banned.
        eligible = [t for t in min_trucks if t not in hard_banned]

        if eligible:
            banned_for_weights = [t for t in assigned_crews if t not in eligible]
            weights = calculate_weights(
                employee_id=walker.id,
                employee_role="walker",
                base_weights=base_weights,
                assigned_crews=assigned_crews,
                banned_truck_ids=banned_for_weights,
                db=db,
            )
        else:
            # Every minimum-count truck is banned — fall back to any unbanned truck.
            fallback = [t for t in assigned_crews if t not in hard_banned]
            if fallback:
                weights = calculate_weights(
                    employee_id=walker.id,
                    employee_role="walker",
                    base_weights=base_weights,
                    assigned_crews=assigned_crews,
                    banned_truck_ids=hard_banned,
                    db=db,
                )
            else:
                weights = {t: 1 for t in assigned_crews}

        truck_ids = list(weights.keys())
        truck_weights = list(weights.values())

        if all(w == 0 for w in truck_weights):
            truck_weights = [1] * len(truck_ids)

        selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
        assigned_crews[selected_truck].append({"id": walker.id, "role": "walker"})

        # Only warn if the walker actually landed on a truck with a banned person.
        # This avoids false positives where the minimum-count trucks were all banned
        # but the walker was successfully placed on a different, unbanned truck.
        if selected_truck in hard_banned:
            banned_by = [banner_id for _, banner_id, _ in raw_bans]
            warnings.append({"employee_id": walker.id, "banned_by": banned_by})

    return warnings
