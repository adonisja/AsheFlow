import random

from sqlalchemy.orm import Session
from app.services.previous_assignment import check_consecutive_assignment

def assign_drivers(
    available_drivers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session
)->None:
    """Assign one driver to each truck using weighted random selection.

    Drivers who were on the same truck in their previous assignment receive a
    significantly lower selection weight to discourage consecutive placement.
    Mutates ``assigned_crews`` in place.

    Args:
        available_drivers: List of Driver Employee ORM objects to assign.
        assigned_crews: Dict mapping truck_id to crew list; updated in place.
        base_weights: Dict mapping truck_id to its base selection weight.
        db: Database session.
    """
    # copy so we can pop drivers out as they're assigned without mutating the caller's list
    remaining_drivers = available_drivers.copy()

    # iterate once per truck — exactly one driver is consumed per loop
    for truck_id in base_weights.keys():
        # build a weight list that mirrors the current remaining_drivers order
        driver_weights = []
        for driver in remaining_drivers:
            # drastically lower the chance of repeating the same driver-truck pair from last dispatch
            if check_consecutive_assignment(driver.id, truck_id, db):
                driver_weights.append(0.05)
            else:
                driver_weights.append(1)

        # weighted random pick — random.choices returns a list, so index [0] to get the element
        selected_driver = random.choices(remaining_drivers, weights=driver_weights)[0]
        # store as a role dict so all downstream crew lookups stay consistent
        assigned_crews[truck_id].append({"id": selected_driver.id, "role": "driver"})
        # remove from pool so this driver can't be double-assigned to another truck
        remaining_drivers.remove(selected_driver)