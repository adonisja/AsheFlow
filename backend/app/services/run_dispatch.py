from datetime import date
from sqlalchemy.orm import Session
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.services.available_pool import get_available_pool
from app.services.base_weights import get_base_weights
from app.services.assign_drivers import assign_drivers
from app.services.assign_trainers import assign_trainers
from app.services.assign_trainees import assign_trainees
from app.services.assign_walkers import assign_walkers
from app.services.graduate_trainees import graduate_eligible_trainees
from app.services.constants import MIN_TRAINERS_PER_TRUCK, MIN_WALKERS_PER_TRUCK
from app.services.rebalance_crews import rebalance_crews
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.training import TrainingRecord


def run_dispatch(db: Session, target_date: date = None, total_employees: int = None, total_trucks: int = None) -> dict:
    target_date = target_date or date.today()

    # Check and graduate any trainees who have completed 5 assignments before generating the pool
    graduation_warnings = graduate_eligible_trainees(db, target_date)

    available_pool = get_available_pool(db, target_date)

    trucks = db.query(Truck).filter(Truck.is_active == True).order_by(Truck.name).all()
    if total_trucks is not None and total_trucks > 0:
        trucks = trucks[:total_trucks]

    truck_ids = [truck.id for truck in trucks]
    num_trucks = len(truck_ids)

    staffing_warnings = []

    # --- Headcount cap: trim pool to total_employees if provided ---
    if total_employees is not None and total_employees > 0:
        current_total = (
            len(available_pool["drivers"])
            + len(available_pool["trainers"])
            + len(available_pool["trainees"])
            + len(available_pool["walkers"])
        )
        if current_total > total_employees:
            allowed_walkers = max(
                0,
                total_employees
                - len(available_pool["drivers"])
                - len(available_pool["trainers"])
                - len(available_pool["trainees"]),
            )
            available_pool["walkers"] = available_pool["walkers"][:allowed_walkers]

            current_total = (
                len(available_pool["drivers"])
                + len(available_pool["trainers"])
                + len(available_pool["trainees"])
            )
            if current_total > total_employees:
                allowed_trainees = max(
                    0,
                    total_employees
                    - len(available_pool["drivers"])
                    - len(available_pool["trainers"]),
                )
                available_pool["trainees"] = available_pool["trainees"][:allowed_trainees]

                current_total = len(available_pool["drivers"]) + len(available_pool["trainers"])
                if current_total > total_employees:
                    allowed_trainers = max(0, total_employees - len(available_pool["drivers"]))
                    available_pool["trainers"] = available_pool["trainers"][:allowed_trainers]

    # --- Driver warning: must have exactly 1 driver per truck ---
    num_drivers = len(available_pool["drivers"])
    if num_drivers < num_trucks:
        missing = num_trucks - num_drivers
        staffing_warnings.append({
            "type": "understaffed_drivers",
            "message": (
                f"Insufficient drivers: {num_drivers} available for {num_trucks} trucks. "
                f"{missing} truck(s) will have no driver. Please assign manually."
            ),
        })

    # --- Trainer / walker warnings only fire when headcount was explicitly capped ---
    # In auto mode (no total_employees), all available staff are distributed evenly
    # so there are no unfilled slots — just fewer per truck.
    if total_employees is not None and total_employees > 0:
        num_trainers = len(available_pool["trainers"])
        num_walkers  = len(available_pool["walkers"])
        if num_trainers < num_trucks * MIN_TRAINERS_PER_TRUCK:
            missing = num_trucks * MIN_TRAINERS_PER_TRUCK - num_trainers
            staffing_warnings.append({
                "type": "understaffed_trainers",
                "message": (
                    f"Only {num_trainers} trainers available for {num_trucks} trucks. "
                    f"{missing} trainer slot(s) will go unfilled."
                ),
            })
        if num_walkers < num_trucks * MIN_WALKERS_PER_TRUCK:
            missing = num_trucks * MIN_WALKERS_PER_TRUCK - num_walkers
            staffing_warnings.append({
                "type": "understaffed_walkers",
                "message": (
                    f"Only {num_walkers} walkers available for {num_trucks} trucks. "
                    f"{missing} walker slot(s) will go unfilled."
                ),
            })

    # --- Cap excess trainers and re-slot them as walkers ---
    # Excess trainers are appended to the walker pool as Employee ORM objects.
    # assign_walkers writes role="walker" into assigned_crews regardless of the
    # ORM object's role field, so no mutation of the Employee object is needed.
    max_trainers_needed = num_trucks * MIN_TRAINERS_PER_TRUCK
    all_trainers = available_pool.get("trainers", [])
    if len(all_trainers) > max_trainers_needed:
        excess_trainers = all_trainers[max_trainers_needed:]
        available_pool["walkers"].extend(excess_trainers)
        available_pool["trainers"] = all_trainers[:max_trainers_needed]

    base_weights = get_base_weights(truck_ids)
    assigned_crews = {truck_id: [] for truck_id in truck_ids}

    assign_drivers(available_pool["drivers"], assigned_crews, base_weights, db)
    trainer_warnings = assign_trainers(available_pool["trainers"], assigned_crews, base_weights, db)

    # --- Continuation request pre-pass ---
    # Build trainer_id -> truck_id from the now-placed trainers.
    trainer_to_truck = {
        m["id"]: truck_id
        for truck_id, crew in assigned_crews.items()
        for m in crew if m["role"] == "trainer"
    }

    # Fetch all accepted continuation requests whose trainee is in today's pool.
    trainee_ids_in_pool = [t.id for t in available_pool["trainees"]]
    accepted_requests = (
        db.query(TrainerContinuationRequest)
        .filter(
            TrainerContinuationRequest.status == "accepted",
            TrainerContinuationRequest.trainee_id.in_(trainee_ids_in_pool),
        )
        .all()
    ) if trainee_ids_in_pool else []

    # Group accepted requests by trainer — multiple trainees may target the same trainer.
    from collections import defaultdict
    from datetime import datetime, timezone
    requests_by_trainer: dict = defaultdict(list)
    for req in accepted_requests:
        requests_by_trainer[req.trainer_id].append(req)

    pulled_trainee_ids: set = set()

    for trainer_id, reqs in requests_by_trainer.items():
        # Trainer must be dispatched to a truck today.
        if trainer_id not in trainer_to_truck:
            # Trainer unavailable — all their accepted requests are nullified,
            # trainees remain in rolling pool.
            for req in reqs:
                req.status = "nullified"
                req.resolved_at = datetime.now(timezone.utc)
            continue

        # Resolve priority ordering for this trainer's requests:
        # 1. Ranked requests first (lower priority integer = higher priority).
        # 2. Unranked (priority is None) treated as lowest.
        # 3. LIFO tiebreaker within same rank tier: most recent TrainingRecord
        #    with this trainer wins (most recently trained together = higher priority).
        def sort_key(req):
            # Most recent record_date where this trainee trained with this trainer
            last_together = (
                db.query(TrainingRecord.record_date)
                .filter(
                    TrainingRecord.trainee_id == req.trainee_id,
                    TrainingRecord.trainer_id == trainer_id,
                )
                .order_by(TrainingRecord.record_date.desc())
                .first()
            )
            lifo_date = last_together[0] if last_together else None
            # Sort: ranked first (None ranks sort last), then most-recent lifo_date desc
            rank = req.priority if req.priority is not None else 999999
            # Negate lifo_date for descending sort using a comparable tuple
            lifo_ts = lifo_date.toordinal() if lifo_date else 0
            return (rank, -lifo_ts)

        sorted_reqs = sorted(reqs, key=sort_key)

        # Only the first (highest priority) trainee gets pulled to this trainer today.
        # Remaining re-enter the rolling pool.
        truck_id = trainer_to_truck[trainer_id]
        winner = sorted_reqs[0]
        losers = sorted_reqs[1:]

        # Pull winner: inject directly into assigned_crews, remove from rolling pool.
        assigned_crews[truck_id].append({
            "id": winner.trainee_id,
            "role": "trainee",
            "paired_trainer_id": trainer_id,
        })
        pulled_trainee_ids.add(winner.trainee_id)
        winner.status = "nullified"
        winner.resolved_at = datetime.now(timezone.utc)

        # Losers: nullify their requests, they rejoin the rolling pool normally.
        for req in losers:
            req.status = "nullified"
            req.resolved_at = datetime.now(timezone.utc)

    # Also nullify any still-pending requests for today's trainees (auto-expiry).
    pending_requests = (
        db.query(TrainerContinuationRequest)
        .filter(
            TrainerContinuationRequest.status == "pending",
            TrainerContinuationRequest.trainee_id.in_(trainee_ids_in_pool),
        )
        .all()
    ) if trainee_ids_in_pool else []
    for req in pending_requests:
        req.status = "nullified"
        req.resolved_at = datetime.now(timezone.utc)

    db.flush()

    # Remove pulled trainees from the rolling pool before Pass 3.
    remaining_trainees = [
        t for t in available_pool["trainees"]
        if t.id not in pulled_trainee_ids
    ]

    trainee_warnings = assign_trainees(remaining_trainees, assigned_crews, db)
    walker_warnings = assign_walkers(available_pool["walkers"], assigned_crews, base_weights, db)
    
    rebalance_moves = rebalance_crews(assigned_crews, db)

    raw_warnings = graduation_warnings + staffing_warnings + trainer_warnings + trainee_warnings + walker_warnings

    # Collect all employee UUIDs referenced in ban/reassignment warnings and bulk-resolve names.
    ref_ids = set()
    for w in raw_warnings:
        if "type" in w and w["type"] in ("ban_override_reassignment",):
            ref_ids.update([w.get("evicted_employee_id"), w.get("in_favour_of_employee_id")])
        elif "employee_id" in w and "type" not in w:
            ref_ids.add(w["employee_id"])
            ref_ids.update(w.get("banned_by", []))
    ref_ids.discard(None)

    name_map: dict = {}
    if ref_ids:
        rows = db.query(Employee.id, Employee.name).filter(Employee.id.in_(ref_ids)).all()
        name_map = {r.id: r.name for r in rows}

    # Resolve truck names for reassignment warnings.
    truck_ids_needed = set()
    for w in raw_warnings:
        if "type" in w and w["type"] == "ban_override_reassignment":
            truck_ids_needed.update([w.get("from_truck_id"), w.get("evicted_to_truck_id")])
    truck_ids_needed.discard(None)

    from app.models.truck import Truck as TruckModel
    truck_name_map: dict = {}
    if truck_ids_needed:
        truck_rows = db.query(TruckModel.id, TruckModel.name).filter(TruckModel.id.in_(truck_ids_needed)).all()
        truck_name_map = {r.id: r.name for r in truck_rows}

    warnings = []
    for w in raw_warnings:
        if "type" in w and w["type"] == "ban_override_reassignment":
            evicted_name = name_map.get(w["evicted_employee_id"], str(w["evicted_employee_id"]))
            favour_name  = name_map.get(w["in_favour_of_employee_id"], str(w["in_favour_of_employee_id"]))
            from_truck   = truck_name_map.get(w["from_truck_id"], str(w["from_truck_id"]))
            to_truck     = truck_name_map.get(w["evicted_to_truck_id"], "another truck") if w.get("evicted_to_truck_id") else "another truck"
            warnings.append({
                "type": "ban_override_reassignment",
                "message": (
                    f"{evicted_name} was moved from {from_truck} to {to_truck} "
                    f"because {favour_name} has a ban conflict with them and is preferred by the driver/trainer."
                ),
            })
        elif "type" not in w and "employee_id" in w:
            # ban-conflict warning — employee could not avoid all bans
            emp_name    = name_map.get(w["employee_id"], str(w["employee_id"]))
            banned_names = [name_map.get(bid, str(bid)) for bid in w.get("banned_by", [])]
            truck_id    = next(
                (tid for tid, crew in assigned_crews.items() if any(m["id"] == w["employee_id"] for m in crew)),
                None,
            )
            placed_truck = truck_name_map.get(truck_id, "a truck") if truck_id else "a truck"
            warnings.append({
                "type": "ban_conflict",
                "message": (
                    f"{emp_name} was placed on {placed_truck} despite a ban conflict"
                    + (f" with {', '.join(banned_names)}" if banned_names else "") + "."
                ),
            })
        else:
            warnings.append(w)

    for truck_id, crew in assigned_crews.items():
        truck_assignment = TruckAssignment(
            truck_id=truck_id,
            date=target_date,
            status="planned"
        )
        db.add(truck_assignment)
        db.flush()

        for member in crew:
            assignment_member = AssignmentMember(
                assignment_id=truck_assignment.id,
                employee_id=member["id"],
                role="walker" if member.get("role") == "walker" else member["role"]
            )
            db.add(assignment_member)

    db.commit()

    formatted_crews = {}
    assignments = db.query(TruckAssignment).filter(TruckAssignment.date == target_date).all()
    for assignment in assignments:
        members_query = db.query(AssignmentMember, Employee).join(
            Employee, AssignmentMember.employee_id == Employee.id
        ).filter(
            AssignmentMember.assignment_id == assignment.id
        ).all()
        
        crew_list = []
        for am, emp in members_query:
            crew_list.append({
                "assignment_id": str(am.id),
                "employee_id": str(emp.id),
                "name": emp.name,
                "role": am.role
            })
            
        formatted_crews[str(assignment.truck_id)] = crew_list

    return formatted_crews, warnings
