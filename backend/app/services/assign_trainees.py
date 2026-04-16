import random
from sqlalchemy.orm import Session


def assign_trainees(
    available_trainees: list,
    assigned_crews: dict,
    db: Session,
) -> list:
    """Assign trainees to trainers (and therefore their trucks) with even distribution.

    Distribution is two-level:

    1. Per-truck minimum first: within each truck, every trainer must have at
       least N trainees before any trainer on that truck is eligible for N+1.
       This prevents Brandon on Truck A from receiving a second trainee while
       Trainer X, also on Truck A, still has zero.

    2. Global minimum second: across all trucks, trainers at the current global
       minimum count are eligible. Trainers on trucks where the intra-truck
       minimum is already satisfied at a higher count are naturally deprioritised
       by the global minimum check.

    The unit of distribution is the trainer, not the truck:
    - Count trainees already paired to each trainer in assigned_crews.
    - Eligible trainers = those at the current global minimum paired-trainee
      count, restricted to trainers whose intra-truck minimum is also satisfied
      (i.e. every other trainer on their truck has at least as many trainees).
    - Pick uniformly at random from eligible trainers.
    - Place the trainee on that trainer's truck in assigned_crews, tagged with
      paired_trainer_id so training_injection and the rebalancer can identify
      the bond without a DB query.

    Trainers with no truck assignment are never eligible (shouldn't be possible
    after assign_trainers runs, but guarded defensively).

    Args:
        available_trainees: List of Trainee Employee ORM objects to assign.
            Trainees already pulled by continuation pre-pass are NOT in this list.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        db: Database session (reserved for future extension; unused currently).

    Returns:
        An empty list (no warnings generated — trainees cannot produce ban conflicts).
    """
    # Build a map: trainer_id -> truck_id from the current assigned_crews state.
    trainer_to_truck = {
        m["id"]: truck_id
        for truck_id, crew in assigned_crews.items()
        for m in crew
        if m["role"] == "trainer"
    }

    if not trainer_to_truck:
        # No trainers dispatched — trainees cannot be placed.
        return []

    # Build the reverse: truck_id -> [trainer_ids on that truck]
    truck_to_trainers: dict = {}
    for t_id, truck_id in trainer_to_truck.items():
        truck_to_trainers.setdefault(truck_id, []).append(t_id)

    trainer_ids = list(trainer_to_truck.keys())

    for trainee in available_trainees:
        # Count how many trainees are currently paired to each trainer.
        paired_counts = {
            t_id: sum(
                1 for m in assigned_crews[trainer_to_truck[t_id]]
                if m.get("paired_trainer_id") == t_id
            )
            for t_id in trainer_ids
        }

        # Global minimum across all trainers.
        global_min = min(paired_counts.values())

        # A trainer is eligible only if:
        #   (a) their own paired count equals the global minimum, AND
        #   (b) every other trainer on their truck has at least as many trainees
        #       (i.e. they are not jumping ahead of a truck-mate who has fewer).
        def is_eligible(t_id: object) -> bool:
            if paired_counts[t_id] != global_min:
                return False
            truck_id = trainer_to_truck[t_id]
            truck_mates = truck_to_trainers[truck_id]
            truck_min = min(paired_counts[mate] for mate in truck_mates)
            # Only eligible if this trainer is at the truck-level minimum too.
            return paired_counts[t_id] == truck_min

        eligible = [t_id for t_id in trainer_ids if is_eligible(t_id)]

        # Fallback: if intra-truck constraint makes nobody eligible (shouldn't
        # happen in normal operation), relax to global minimum only.
        if not eligible:
            eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == global_min]

        selected_trainer_id = random.choice(eligible)
        truck_id = trainer_to_truck[selected_trainer_id]

        assigned_crews[truck_id].append({
            "id": trainee.id,
            "role": "trainee",
            "paired_trainer_id": selected_trainer_id,
        })

    return []
