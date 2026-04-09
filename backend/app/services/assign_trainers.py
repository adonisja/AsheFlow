import random
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.employee_relationship import EmployeeRelationship
from app.services.calculate_weights import calculate_weights
from app.services.constants import MIN_TRAINERS_PER_TRUCK

def assign_trainers(
    available_trainers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session
) -> list:
    """Assign trainers to trucks using weighted random selection with ban and cap enforcement.

    Respects ban relationships against assigned drivers, enforces the minimum
    trainers-per-truck target during a first pass, and falls back to uniform
    weights when all trucks are banned for a trainer.  Mutates ``assigned_crews``
    in place.

    Args:
        available_trainers: List of Trainer Employee ORM objects to assign.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        base_weights: Dict mapping truck_id to its base selection weight.
        db: Database session.

    Returns:
        A list of warning dicts for trainers who could not avoid all bans,
        each with keys ``"employee_id"`` and ``"banned_by"``.
    """
    # copy so we can iterate without mutating the caller's list
    remaining_trainers = available_trainers.copy()
    warnings = []

    # invert assigned_crews into driver_id → truck_id for O(1) ban-truck lookups below
    driver_to_truck = {
        c["id"]: truck_id for truck_id, crew in assigned_crews.items()
        for c in crew if c["role"] == "driver"
    }

    # fetch all ban records involving any assigned driver in a single query rather than per-trainer
    ban_records = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            # bans are bidirectional in data — check both columns so we catch initiator and target
            or_(
                EmployeeRelationship.employee_id.in_(driver_to_truck.keys()),
                EmployeeRelationship.target_employee_id.in_(driver_to_truck.keys())
            )
        ).all()
    )

    # pre-build a map of trainer_id → [truck_ids they're banned from] before the assignment loop
    banned_trucks_by_trainer = {}
    for ban in ban_records:
        # determine which side of the ban is the driver (already placed) and which is the trainer
        if ban.employee_id in driver_to_truck:
            truck_id = driver_to_truck[ban.employee_id]
            banned_trucks_by_trainer.setdefault(ban.target_employee_id, []).append(truck_id)
        else:
            truck_id = driver_to_truck[ban.target_employee_id]
            banned_trucks_by_trainer.setdefault(ban.employee_id, []).append(truck_id)

    for trainer in remaining_trainers:
        # recount per iteration because prior iterations change the distribution
        trainer_counts = {
            truck_id: sum(1 for c in crew if c["role"] == "trainer")
            for truck_id, crew in assigned_crews.items()
        }

        # first pass: spread trainers evenly before allowing any truck to exceed the minimum
        first_pass_active = any(count < MIN_TRAINERS_PER_TRUCK for count in trainer_counts.values())

        # treat already-full trucks as temporarily banned so the spread enforces the minimum
        capped_trucks = [
            truck_id for truck_id, count in trainer_counts.items()
            if first_pass_active and count >= MIN_TRAINERS_PER_TRUCK
        ]

        # merge ban conflicts and spread caps into one list for calculate_weights
        banned_truck_ids = banned_trucks_by_trainer.get(trainer.id, []) + capped_trucks

        weights = calculate_weights(
            employee_id=trainer.id,
            employee_role="trainer",
            base_weights=base_weights,
            assigned_crews=assigned_crews,
            banned_truck_ids=banned_truck_ids,
            db=db
        )

        truck_ids = list(weights.keys())
        truck_weights = list(weights.values())

        # all-zero means every truck is banned — record a warning and fall back to uniform weights
        if all(w == 0 for w in truck_weights):
            # collect the IDs of whoever caused the ban conflict for the warning payload
            banned_by = [
                ban.employee_id if ban.employee_id not in driver_to_truck else ban.target_employee_id
                for ban in ban_records
                if ban.target_employee_id == trainer.id or ban.employee_id == trainer.id
            ]
            warnings.append({"employee_id": trainer.id, "banned_by": banned_by})
            # uniform fallback ensures the trainer still gets placed despite the conflict
            truck_weights = [1] * len(truck_ids)

        selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
        assigned_crews[selected_truck].append({"id": trainer.id, "role": "trainer"})

    return warnings
