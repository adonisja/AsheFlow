import random
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.employee_relationship import EmployeeRelationship
from app.services.calculate_weights import calculate_weights
from app.services.company_config import ResolvedConfig


def assign_trainers(
    available_trainers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session,
    cfg: ResolvedConfig = None,
) -> list:
    """Assign trainers to trucks with guaranteed even distribution.

    Enforces a hard round-robin spread: a trainer is only eligible for trucks
    that are currently at the minimum trainer count.  Ban / fav / consecutive
    logic still runs within that eligible set.  Only if every minimum-count
    truck is banned for a trainer do we open up above-minimum trucks as a
    fallback, and a warning is recorded.

    Args:
        available_trainers: List of Trainer Employee ORM objects to assign.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        base_weights: Dict mapping truck_id to its base selection weight.
        db: Database session.

    Returns:
        A list of warning dicts for trainers who could not avoid all bans.
    """
    remaining_trainers = available_trainers.copy()
    warnings = []

    # Build driver→truck map for ban lookups (only drivers are placed before trainers).
    driver_to_truck = {
        c["id"]: truck_id
        for truck_id, crew in assigned_crews.items()
        for c in crew if c["role"] == "driver"
    }

    ban_records = (
        db.query(EmployeeRelationship)
        .filter(
            EmployeeRelationship.relationship_type == "ban",
            or_(
                EmployeeRelationship.employee_id.in_(driver_to_truck.keys()),
                EmployeeRelationship.target_employee_id.in_(driver_to_truck.keys()),
            ),
        )
        .all()
    ) if driver_to_truck else []

    banned_trucks_by_trainer: dict = {}
    for ban in ban_records:
        if ban.employee_id in driver_to_truck:
            truck_id = driver_to_truck[ban.employee_id]
            banned_trucks_by_trainer.setdefault(ban.target_employee_id, []).append(truck_id)
        else:
            truck_id = driver_to_truck[ban.target_employee_id]
            banned_trucks_by_trainer.setdefault(ban.employee_id, []).append(truck_id)

    for trainer in remaining_trainers:
        # Recount after every placement so the minimum is always current.
        trainer_counts = {
            truck_id: sum(1 for c in crew if c["role"] == "trainer")
            for truck_id, crew in assigned_crews.items()
        }

        min_count = min(trainer_counts.values()) if trainer_counts else 0
        # Hard eligibility: only trucks currently at the minimum.
        min_trucks = [t for t, cnt in trainer_counts.items() if cnt == min_count]

        raw_banned = banned_trucks_by_trainer.get(trainer.id, [])

        # Try to place on a minimum truck that isn't banned.
        eligible = [t for t in min_trucks if t not in raw_banned]

        if eligible:
            # Run fav/consecutive weights only over the eligible even-distribution set.
            weights = calculate_weights(
                employee_id=trainer.id,
                employee_role="trainer",
                base_weights=base_weights,
                assigned_crews=assigned_crews,
                banned_truck_ids=[t for t in assigned_crews if t not in eligible],
                db=db,
                cfg=cfg,
            )
        else:
            # Every minimum truck is banned — fall back to any unbanned truck.
            all_trucks = list(assigned_crews.keys())
            fallback = [t for t in all_trucks if t not in raw_banned]

            banned_by = [
                ban.employee_id if ban.employee_id not in driver_to_truck else ban.target_employee_id
                for ban in ban_records
                if ban.target_employee_id == trainer.id or ban.employee_id == trainer.id
            ]
            warnings.append({"employee_id": trainer.id, "banned_by": banned_by})

            if fallback:
                weights = calculate_weights(
                    employee_id=trainer.id,
                    employee_role="trainer",
                    base_weights=base_weights,
                    assigned_crews=assigned_crews,
                    banned_truck_ids=raw_banned,
                    db=db,
                    cfg=cfg,
                )
            else:
                # Fully banned everywhere — uniform fallback so dispatch still completes.
                weights = {t: 1 for t in all_trucks}

        truck_ids = list(weights.keys())
        truck_weights = list(weights.values())

        if all(w == 0 for w in truck_weights):
            truck_weights = [1] * len(truck_ids)

        selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
        assigned_crews[selected_truck].append({"id": trainer.id, "role": "trainer"})

    return warnings
