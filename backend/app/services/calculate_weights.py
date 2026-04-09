from uuid import UUID

from sqlalchemy.orm import Session
from app.services.previous_assignment import check_consecutive_assignment
from app.services.fans_list import get_fans
from app.services.resolve_conflict import resolve_conflict
from app.services.tridirectional import perform_tridirectional_check
from app.services.bidirectional import perform_bidirectional_check
from app.services.constants import ROLE_BOOST, MUTUAL_BONUS

def calculate_weights(
    employee_id: UUID,
    employee_role: str,
    base_weights: dict,        # {truck_id: base_weight} from get_base_weights
    assigned_crews: dict,      # {truck_id: [{"id": employee_id, "role": "driver"}, ...]} — who's already on each truck
    banned_truck_ids: list,    # trucks where a ban conflict exists
    db: Session
) -> dict:                      # {truck_id: final_weight}
    """Compute per-truck selection weights for a candidate employee.

    Starts from ``base_weights``, zeroes out banned trucks, applies a
    consecutive-assignment penalty, then boosts trucks where existing crew
    members are fans of the candidate.  Bidirectional and tridirectional mutual
    favourites receive additional bonus weight.

    Args:
        employee_id: UUID of the candidate employee.
        employee_role: Role of the candidate (``"driver"``, ``"trainer"``, or
            ``"walker"``).
        base_weights: Dict mapping truck_id to its initial equal weight.
        assigned_crews: Dict mapping truck_id to a list of crew dicts
            ``{"id": employee_id, "role": str}``.
        banned_truck_ids: List of truck IDs the candidate must not be assigned to.
        db: Database session.

    Returns:
        A dict mapping each truck_id to its final selection weight.
    """
    
    # work on a copy so the caller's base_weights dict is never modified
    base_weights_copy = base_weights.copy()

    # first pass: zero out banned trucks and apply consecutive-assignment penalty to the rest
    for truck_id in base_weights.keys():
        if truck_id in banned_truck_ids:
            # hard zero so random.choices never selects this truck
            base_weights_copy[truck_id] = 0
        else:
            # discourage repeating the exact same truck as the previous dispatch, but don't forbid it
            consecutive_assignment = check_consecutive_assignment(employee_id, truck_id, db)
            if consecutive_assignment:
                base_weights_copy[truck_id] *= 0.05

    # get_fans returns {truck_id: [fan_ids]} — fans are already-placed crew members who listed
    # the candidate in their fav list
    fans_by_truck = get_fans(employee_id, assigned_crews, db)

    # bucket fan trucks by the fan's role so different ROLE_BOOST multipliers apply per role
    fans_by_role = {
        "driver": [],
        "trainer": [],
        "walker": []
    }

    for truck_id, fan_ids in fans_by_truck.items():
        for fan_id in fan_ids:
            # look up this fan's role from the already-assigned crew list
            role = next(c["role"] for c in assigned_crews[truck_id] if c["id"] == fan_id)
            fans_by_role[role].append(truck_id)

    # apply boost per role — if multiple trucks have fans of the same role, resolve the conflict
    for role in fans_by_role:
        boosted_truck_id = None

        # skip trucks that are banned — a fan on a banned truck can't pull the candidate there
        eligible_trucks = list(set(t for t in fans_by_role[role] if t not in banned_truck_ids))

        if len(eligible_trucks) > 1:
            # multiple trucks have fans of this role — ask resolve_conflict to pick one based on
            # stronger mutual preference signals; if it can't decide, split the boost evenly
            conflict_ids = [
                (truck_id, fans_by_truck[truck_id][0]) for truck_id in eligible_trucks
            ]
            truck_id = resolve_conflict(employee_id, conflict_ids, db)

            if truck_id:
                # a clear winner — concentrate the full boost on that truck
                base_weights_copy[truck_id] += (base_weights_copy[truck_id] * ROLE_BOOST[role])
                boosted_truck_id = truck_id

            else:
                # no clear winner — spread the boost proportionally so no truck is unfairly favored
                length = len(eligible_trucks)
                split = ROLE_BOOST[role] / length
                for t_id in eligible_trucks:
                    base_weights_copy[t_id] += base_weights_copy[t_id] * split

        elif len(eligible_trucks) == 1:
            # unambiguous — apply the full role boost directly
            t = eligible_trucks[0]
            base_weights_copy[t] += (base_weights_copy[t] * ROLE_BOOST[role])
            boosted_truck_id = t

        if boosted_truck_id:
            fan_id = fans_by_truck[boosted_truck_id][0]

            if employee_role == "walker":
                # walkers can earn a tridirectional bonus when the driver AND trainer both fav them —
                # a stronger signal than a single bidirectional relationship
                driver_id = next((c["id"] for c in assigned_crews[boosted_truck_id] if c["role"] == "driver"), None)
                trainer_id = next((c["id"] for c in assigned_crews[boosted_truck_id] if c["role"] == "trainer"), None)

                if driver_id and trainer_id and perform_tridirectional_check(driver_id, trainer_id, employee_id, db):
                    base_weights_copy[boosted_truck_id] += MUTUAL_BONUS["tridirectional"]
                elif perform_bidirectional_check(employee_id, fan_id, db):
                    # mutual fav between candidate and the fan earns a bidirectional bonus
                    base_weights_copy[boosted_truck_id] += MUTUAL_BONUS["bidirectional"]

            else:
                # drivers and trainers are only eligible for the bidirectional bonus
                if perform_bidirectional_check(employee_id, fan_id, db):
                    base_weights_copy[boosted_truck_id] += MUTUAL_BONUS["bidirectional"]

