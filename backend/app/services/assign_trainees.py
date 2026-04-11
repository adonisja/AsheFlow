import random
from sqlalchemy.orm import Session


def assign_trainees(
    available_trainees: list,
    assigned_crews: dict,
    db: Session,
) -> list:
    """Assign trainees to trainers (and therefore their trucks) with even distribution.

    Trainees have no fav/ban list — assignment is a uniform random round-robin
    over trainers. The unit of distribution is the trainer, not the truck:

    - Count trainees already paired to each trainer in assigned_crews.
    - Eligible trainers = those at the current minimum paired-trainee count.
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

        min_count = min(paired_counts.values())
        eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == min_count]

        selected_trainer_id = random.choice(eligible)
        truck_id = trainer_to_truck[selected_trainer_id]

        assigned_crews[truck_id].append({
            "id": trainee.id,
            "role": "trainee",
            "paired_trainer_id": selected_trainer_id,
        })

    return []
