from datetime import date

from sqlalchemy.orm import Session

from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.services.available_pool import get_available_pool
from app.services.base_weights import get_base_weights
from app.services.assign_drivers import assign_drivers
from app.services.assign_trainers import assign_trainers
from app.services.assign_walkers import assign_walkers
from app.services.constants import MIN_TRAINERS_PER_TRUCK, MIN_WALKERS_PER_TRUCK


def run_dispatch(db: Session, target_date: date = None) -> dict:
    """Execute the full dispatch pipeline for a given date and persist the results.

    Fetches active trucks and the available employee pool, validates driver
    sufficiency, then assigns drivers, trainers, and walkers in order.
    Committed truck assignments and assignment members are written to the database.

    Args:
        db: Database session.
        target_date: Date to run dispatch for. Defaults to today.

    Returns:
        A tuple of ``(assigned_crews, warnings)`` where ``assigned_crews`` is a
        dict mapping truck_id to a list of crew dicts ``{"id": ..., "role": ...}``,
        and ``warnings`` is a list of staffing or ban-conflict warning dicts.

    Raises:
        ValueError: If there are fewer available drivers than active trucks.
    """
    target_date = target_date or date.today()

    # only dispatch active trucks — inactive trucks are excluded from today's pool
    trucks = db.query(Truck).filter(Truck.is_active == True).all()
    truck_ids = [truck.id for truck in trucks]

    # all trucks start with equal weight; assignment services will adjust from here
    base_weights = get_base_weights(truck_ids)
    # initialize empty crew lists so assignment functions can append without key errors
    assigned_crews = {truck_id: [] for truck_id in truck_ids}

    # available_pool = {"drivers": [...], "trainers": [...], "walkers": [...]}
    # excludes employees on approved days off for target_date
    available_pool = get_available_pool(db, target_date)

    # drivers are hard-required: one per truck, no fallback — raise early to prevent partial state
    num_trucks = len(truck_ids)
    num_drivers = len(available_pool["drivers"])
    if num_drivers < num_trucks:
        missing = num_trucks - num_drivers
        raise ValueError(
            f"Insufficient drivers: {num_drivers} available for {num_trucks} trucks. "
            f"{missing} slot(s) require manual assignment before dispatch can run."
        )

    # trainer/walker shortfalls don't block dispatch — trucks can run understaffed, but ops should know
    staffing_warnings = []
    num_trainers = len(available_pool["trainers"])
    num_walkers = len(available_pool["walkers"])

    if num_trainers < num_trucks * MIN_TRAINERS_PER_TRUCK:
        missing = num_trucks * MIN_TRAINERS_PER_TRUCK - num_trainers
        staffing_warnings.append({
            "type": "understaffed_trainers",
            "message": f"Only {num_trainers} trainers available for {num_trucks} trucks. {missing} trainer slot(s) will go unfilled."
        })

    if num_walkers < num_trucks * MIN_WALKERS_PER_TRUCK:
        missing = num_trucks * MIN_WALKERS_PER_TRUCK - num_walkers
        staffing_warnings.append({
            "type": "understaffed_walkers",
            "message": f"Only {num_walkers} walkers available for {num_trucks} trucks. {missing} walker slot(s) will go unfilled."
        })

    # order matters: trainers need drivers already placed so ban checks reference real truck occupants,
    # and walkers need both drivers and trainers placed for tridirectional/override logic
    assign_drivers(available_pool["drivers"], assigned_crews, base_weights, db)
    trainer_warnings = assign_trainers(available_pool["trainers"], assigned_crews, base_weights, db)
    walker_warnings = assign_walkers(available_pool["walkers"], assigned_crews, base_weights, db)
    # merge all warning types into one list for the response — staffing warnings have a "type" key,
    # ban-conflict warnings have "employee_id" / "banned_by"
    warnings = staffing_warnings + trainer_warnings + walker_warnings

    # write one TruckAssignment row per truck, then one AssignmentMember row per crew member
    for truck_id, crew in assigned_crews.items():
        truck_assignment = TruckAssignment(
            truck_id=truck_id,
            date=target_date,
            status="planned"
        )
        db.add(truck_assignment)
        # flush to generate truck_assignment.id without committing, so members can reference it
        db.flush()

        for member in crew:
            assignment_member = AssignmentMember(
                assignment_id=truck_assignment.id,
                employee_id=member["id"],
                role=member["role"]
            )
            db.add(assignment_member)

    # single commit for the whole dispatch — keeps the DB consistent if anything fails mid-write
    db.commit()

    return assigned_crews, warnings
