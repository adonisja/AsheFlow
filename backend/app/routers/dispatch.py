import os
from datetime import date
from typing import List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_current_user, get_caller_employee, RoleChecker
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.dispatch_confirmation import DispatchConfirmation
from app.models.notification import Notification
from app.schemas.dispatch import ManualAssignmentCreate, ManualAssignmentUpdate, DispatchConfig
from app.schemas.manifest import PackageManifestCreate, PackageManifestPatch, PackageManifestResponse
from app.models.package_manifest import PackageManifest
from app.services.run_dispatch import run_dispatch
from app.services.available_pool import get_unavailable_staff
from app.services.training_injection import inject_curriculum
from app.services.company_config import get_company_config
from app.models.training import TrainingRecord
from app.core.redis import set_confirmation, get_all_confirmations, seed_pending
from app.services.constants import (
    ROLE_DRIVER, ROLE_TRAINER, ROLE_TRAINEE, ROLE_WALKER,
    ROLE_DISPATCH, ROLE_ADMIN, OVERSIGHT_ROLES,
)
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# Dispatch operations are limited to dispatch role and admin only.
# Management (supervisory) accesses fleet data via reporting endpoints, not the operational dispatch tool.
allow_dispatch_mgmt = RoleChecker([ROLE_DISPATCH, ROLE_ADMIN])

@router.get("/unavailable-staff/{dispatch_date}", status_code=status.HTTP_200_OK)
def get_unavailable_staff_for_date(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    roles: List[str] = Query(default=["driver", "trainer", "walker"]),
):
    """Return active field staff excluded from the available pool on a given date.

    Used by the dispatch UI to surface a call-in list when understaffed warnings fire.
    Trainees are always excluded — their flow is managed by the training system.

    Query params:
        roles: One or more of driver, trainer, walker. Defaults to all three.
               e.g. ?roles=driver&roles=trainer

    Returns contact info (name, discord_id, phone_number) and exclusion reason
    (time_off_request | recurring_off_day) per employee.

    Always queryable — including after dispatch has run and warnings are gone.
    """
    return {
        "date": dispatch_date,
        "unavailable_staff": get_unavailable_staff(db, dispatch_date, roles=roles, company_id=caller.company_id),
    }


@router.get("/{dispatch_date}", status_code=status.HTTP_200_OK)
def get_daily_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Retrieve all truck assignments and their crews for a specific date."""

    assignments = db.query(TruckAssignment).filter(
        TruckAssignment.date == dispatch_date,
        TruckAssignment.company_id == caller.company_id,
    ).all()
    
    if not assignments:
        return {
            "date": dispatch_date,
            "assigned_crews": {},
            "warnings": []
        }
        
    assigned_crews = {}
    
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
                "role": am.role,
                "discord_id": emp.discord_id,
            })
            
        assigned_crews[str(assignment.truck_id)] = crew_list

    truck_statuses = [
        {"truck_id": str(a.truck_id), "status": a.status}
        for a in assignments
    ]

    return {
        "date": dispatch_date,
        "assigned_crews": assigned_crews,
        "truck_assignments": truck_statuses,
        "warnings": []
    }

@router.post("/", status_code=status.HTTP_201_CREATED)
def trigger_dispatch(
    config: Optional[DispatchConfig] = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Run today's dispatch if one does not already exist."""

    target_date = config.date if config and config.date else date.today()

    # prevent double-dispatch — if any TruckAssignment row exists for today, reject immediately
    existing = db.query(TruckAssignment).filter(
        TruckAssignment.date == target_date,
        TruckAssignment.company_id == caller.company_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dispatch already exists for {target_date}"
        )

    # ValueError is raised by run_dispatch when there aren't enough drivers to cover all trucks
    try:
        total_employees = config.total_employees if config else None
        total_trucks = config.total_trucks if config else None

        if not total_trucks or total_trucks <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Total number of trucks is required to run dispatch."
            )

        assigned_crews, warnings = run_dispatch(db, target_date, total_employees, total_trucks, company_id=caller.company_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Persist ban override events as system notifications so analytics can query them.
    # These are dispatch-internal — employee_id is set to a dispatch/admin recipient so
    # they don't surface in field staff notification feeds.
    override_recipients = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(list(OVERSIGHT_ROLES)),
        Employee.is_active == True,
    ).limit(1).all()  # just need one row to satisfy the FK; analytics filters by type

    for w in warnings:
        if w.get("type") == "ban_override_reassignment" and override_recipients:
            evicted_id  = w.get("evicted_employee_id")
            favoured_id = w.get("in_favour_of_employee_id")
            from_truck  = w.get("from_truck_id")
            db.add(Notification(
                company_id=caller.company_id,
                employee_id=override_recipients[0].id,
                type="ban_override_reassignment",
                message=(
                    f"Ban override on {target_date}: walker {evicted_id} evicted from truck "
                    f"{from_truck} in favour of {favoured_id}."
                ),
            ))
    if any(w.get("type") == "ban_override_reassignment" for w in warnings):
        db.commit()

    # All warnings are now normalized dicts with "type" and "message" string fields.
    # Convert any residual UUID values to str for JSON safety.
    serialized_warnings = []
    for w in warnings:
        serialized_warnings.append({k: str(v) if hasattr(v, "hex") else v for k, v in w.items()})

    return {
        "date": target_date,
        # truck_id keys are UUIDs — cast to str so FastAPI can serialize them as JSON object keys
        "assigned_crews": {str(k): v for k, v in assigned_crews.items()},
        "warnings": serialized_warnings
    }

@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def manual_assignment(
    assignment_in: ManualAssignmentCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Manually assign an employee to a truck for a given date.

    Useful when standard dispatch cannot run or when overriding an existing assignment.

    Args:
        assignment_in: Payload containing ``employee_id``, ``truck_id``, ``date``, and ``role``.
        db: Database session injected by FastAPI.
        current_user: Authenticated user dict injected by FastAPI.

    Returns:
        A dict with a ``message`` and an ``assignment`` object containing
        ``assignment_id``, ``employee_id``, ``truck_id``, ``role``, and ``date``.

    Raises:
        HTTPException(404): If the employee or truck does not exist.
        HTTPException(409): If the employee is already assigned on the given date.
    """
    # Verify employee exists within this company
    employee = db.query(Employee).filter(
        Employee.id == assignment_in.employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {assignment_in.employee_id} not found"
        )

    # Verify truck exists within this company
    truck = db.query(Truck).filter(
        Truck.id == assignment_in.truck_id,
        Truck.company_id == caller.company_id,
    ).first()
    if not truck:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Truck {assignment_in.truck_id} not found"
        )
        
    # Check if a dispatch run is already scheduled for that day
    truck_assignment = db.query(TruckAssignment).filter(
        TruckAssignment.date == assignment_in.date,
        TruckAssignment.truck_id == assignment_in.truck_id
    ).first()
    
    if not truck_assignment:
        truck_assignment = TruckAssignment(
            company_id=caller.company_id,
            truck_id=assignment_in.truck_id,
            date=assignment_in.date,
        )
        db.add(truck_assignment)
        db.flush()

    # Prevent assigning an employee to the same truck/date twice or on two different trucks
    existing_assignment = db.query(AssignmentMember).join(TruckAssignment).filter(
        AssignmentMember.employee_id == assignment_in.employee_id,
        TruckAssignment.date == assignment_in.date
    ).first()
    
    if existing_assignment:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Employee {assignment_in.employee_id} is already assigned on {assignment_in.date}"
        )
        
    # Handle Trainee Bumping Logic
    if assignment_in.role == ROLE_TRAINEE:
        # Check if the truck already has a trainee
        existing_trainee_assignment = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == truck_assignment.id,
            AssignmentMember.role == ROLE_TRAINEE
        ).first()

        if existing_trainee_assignment:
            bumped_trainee_id = existing_trainee_assignment.employee_id
            db.delete(existing_trainee_assignment)
            db.flush()

            # Find a fallback truck within this company for the bumped trainee.
            # Priority 1: a truck that has a trainer and no current trainee.
            # Priority 2: any truck that has no current trainee (trainer may arrive later).
            # Both loops exclude the destination truck (the one we're assigning into).
            all_truck_assignments = db.query(TruckAssignment).filter(
                TruckAssignment.date == assignment_in.date,
                TruckAssignment.company_id == caller.company_id,
            ).all()

            fallback_assignment_id = None
            for ta in all_truck_assignments:
                if ta.id == truck_assignment.id:
                    continue
                members = db.query(AssignmentMember).filter(
                    AssignmentMember.assignment_id == ta.id
                ).all()
                has_trainer = any(m.role == ROLE_TRAINER for m in members)
                has_trainee = any(m.role == ROLE_TRAINEE for m in members)
                if has_trainer and not has_trainee:
                    fallback_assignment_id = ta.id
                    break

            if not fallback_assignment_id:
                for ta in all_truck_assignments:
                    if ta.id == truck_assignment.id:
                        continue
                    members = db.query(AssignmentMember).filter(
                        AssignmentMember.assignment_id == ta.id
                    ).all()
                    has_trainee = any(m.role == ROLE_TRAINEE for m in members)
                    if not has_trainee:
                        fallback_assignment_id = ta.id
                        break

            if fallback_assignment_id:
                db.add(AssignmentMember(
                    assignment_id=fallback_assignment_id,
                    employee_id=bumped_trainee_id,
                    role=ROLE_TRAINEE,
                ))
            else:
                # No fallback slot — trainee cannot be placed. Notify oversight staff
                # and the trainee directly. The trainee has no assignment for this date.
                bumped_emp = db.query(Employee).filter(
                    Employee.id == bumped_trainee_id,
                    Employee.company_id == caller.company_id,
                ).first()
                bumped_name = bumped_emp.name if bumped_emp else str(bumped_trainee_id)
                incoming_emp = db.query(Employee).filter(
                    Employee.id == assignment_in.employee_id,
                    Employee.company_id == caller.company_id,
                ).first()
                incoming_name = incoming_emp.name if incoming_emp else str(assignment_in.employee_id)
                alert_staff = (
                    db.query(Employee)
                    .filter(
                        Employee.company_id == caller.company_id,
                        Employee.role.in_(list(OVERSIGHT_ROLES)),
                        Employee.is_active == True,
                    )
                    .all()
                )
                for staff in alert_staff:
                    db.add(Notification(
                        employee_id=staff.id,
                        type="trainee_unassigned",
                        message=(
                            f"⚠️ Trainee unassigned: {bumped_name} was bumped from their truck "
                            f"to make room for {incoming_name} but no free trainer slot was found. "
                            f"Manual reassignment required for {assignment_in.date}."
                        ),
                        dispatch_date=assignment_in.date,
                    ))
                if bumped_emp:
                    db.add(Notification(
                        employee_id=bumped_trainee_id,
                        type="trainee_unassigned",
                        message=(
                            f"Your assignment for {assignment_in.date} was removed due to a reassignment. "
                            f"Dispatch has been notified and will place you manually."
                        ),
                        dispatch_date=assignment_in.date,
                    ))


    new_member = AssignmentMember(
        assignment_id=truck_assignment.id,
        employee_id=assignment_in.employee_id,
        role=assignment_in.role,
        is_manual=True,   # explicitly placed by dispatch after the algorithm ran
    )
    db.add(new_member)

    # Seed a pending confirmation if none exists yet — handles the case where
    # the employee was added after Publish (so they were never seeded by publish_dispatch).
    existing_conf = db.query(DispatchConfirmation).filter(
        DispatchConfirmation.employee_id == assignment_in.employee_id,
        DispatchConfirmation.date == assignment_in.date,
    ).first()
    if not existing_conf:
        db.add(DispatchConfirmation(
            employee_id=assignment_in.employee_id,
            date=assignment_in.date,
            status="pending",
            source="manual_assignment",
        ))

    db.commit()
    db.refresh(new_member)

    # Mirror the pending status into Redis so the confirmations endpoint stays consistent.
    try:
        await set_confirmation(str(assignment_in.date), str(assignment_in.employee_id), "pending")
    except Exception:
        pass  # Redis unavailable — DB row is authoritative

    return {
        "message": "Manual assignment successful",
        "assignment": {
            "assignment_id": str(truck_assignment.id),
            "employee_id": str(new_member.employee_id),
            "truck_id": str(truck_assignment.truck_id),
            "role": new_member.role,
            "date": truck_assignment.date.isoformat()
        }
    }

@router.delete("/assign/{date}/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    date: date,
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Remove an employee from a dispatch run.

    Args:
        date: The dispatch date to remove the employee from.
        employee_id: UUID string of the employee to remove.
        db: Database session injected by FastAPI.
        current_user: Authenticated user dict injected by FastAPI.

    Raises:
        HTTPException(404): If the employee is not scheduled on the given date.
    """
    
    # Step 1: Query the database to find the exact AssignmentMember record
    # Since date is on TruckAssignment, we join the two tables to filter
    target_member = db.query(AssignmentMember).join(TruckAssignment).filter(
        AssignmentMember.employee_id == employee_id,
        TruckAssignment.date == date,
        TruckAssignment.company_id == caller.company_id,
    ).first()
    
    # Step 2: If we don't find them, raise an explicit 404 error
    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {employee_id} is not scheduled on {date}."
        )
        
    # Step 3: Delete the record and commit to the database
    db.delete(target_member)
    db.commit()
    
    return

@router.patch("/assign", status_code=status.HTTP_200_OK)
def swap_assignment(
    assignment_in: ManualAssignmentUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Swap an employee to a different truck after dispatch has run.

    Args:
        assignment_in: Payload containing ``employee_id``, ``date``, ``new_truck_id``,
            and optional ``new_role``.
        db: Database session injected by FastAPI.
        current_user: Authenticated user dict injected by FastAPI.

    Returns:
        A dict with a ``message`` and an ``assignment`` object containing
        ``assignment_id``, ``employee_id``, ``truck_id``, ``role``, and ``date``.

    Raises:
        HTTPException(404): If the employee is not scheduled on the given date, or
            the destination truck does not exist.
        HTTPException(400): If the employee is already on the destination truck with
            the same role.
    """
    
    # Step 1: Guarantee the employee is currently assigned on this date
    target_member = db.query(AssignmentMember).join(TruckAssignment).filter(
        AssignmentMember.employee_id == assignment_in.employee_id,
        TruckAssignment.date == assignment_in.date,
        TruckAssignment.company_id == caller.company_id,
    ).first()

    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {assignment_in.employee_id} is not scheduled on {assignment_in.date}."
        )

    # Step 2: Guarantee the target truck exists within this company
    destination_truck = db.query(Truck).filter(
        Truck.id == assignment_in.new_truck_id,
        Truck.company_id == caller.company_id,
    ).first()
    if not destination_truck:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target Truck {assignment_in.new_truck_id} does not exist."
        )

    # Step 3: Find out if the destination truck already has a TruckAssignment for today.
    destination_assignment = db.query(TruckAssignment).filter(
        TruckAssignment.date == assignment_in.date,
        TruckAssignment.truck_id == assignment_in.new_truck_id
    ).first()
    
    #   If it does NOT exist, we create one and add it to the db, and flush()!
    if not destination_assignment:
        destination_assignment = TruckAssignment(
            company_id=caller.company_id,
            truck_id=assignment_in.new_truck_id,
            date=assignment_in.date,
        )
        db.add(destination_assignment)
    
    # KEY ARCHITECTURE POINT: We MUST call db.flush() here.
        # Why? Because destination_assignment needs a UUID primary key (id) generated by the database
        # BEFORE we can assign it to our target_member. flush() sends the INSERT to Postgres but 
        # doesn't commit the transaction yet.
        db.flush() 

    # Alert the user if trying to move to the exact same truck and role
    if target_member.assignment_id == destination_assignment.id:
        if not assignment_in.new_role or assignment_in.new_role == target_member.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee {assignment_in.employee_id} is already assigned to this truck with this role. Reassignment rejected."
            )
    
     # Step 4: Update the target_member to point to the correct TruckAssignment
    #   and optionally update their role if a new_role was provided.
    target_member.assignment_id = destination_assignment.id
    
    if assignment_in.new_role:
        target_member.role = assignment_in.new_role
        
    db.commit()
    db.refresh(target_member)
    
    return {
        "message": "Employee reassigned successfully",
        "assignment": {
            "assignment_id": str(target_member.assignment_id),
            "employee_id": str(target_member.employee_id),
            "truck_id": str(destination_truck.id),
            "role": target_member.role,
            "date": assignment_in.date.isoformat()
        }
    }


@router.post("/{dispatch_date}/publish", status_code=status.HTTP_200_OK)
async def publish_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Publish the day's dispatch to Discord.

    Seeds all assigned employees as 'pending' in Redis, then fires an
    internal webhook to the bot so it posts embeds and sends DMs.
    """
    logger.info("publish_dispatch started date=%s publisher=%s", dispatch_date, caller.username or str(caller.id))

    assignments = db.query(TruckAssignment).filter(
        TruckAssignment.date == dispatch_date,
        TruckAssignment.company_id == caller.company_id,
    ).all()
    if not assignments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dispatch found for {dispatch_date}. Run dispatch first.",
        )

    # Build a full picture of truck → members with roles and truck names
    # so we can apply the same information-split as the bot DMs.
    truck_map = {
        str(t.id): t
        for t in db.query(Truck).all()
    }

    # Collect all assignments with role + truck context
    crew_by_assignment: list[tuple[AssignmentMember, Employee, Truck]] = []
    all_employee_ids: list[str] = []
    # assigned_crews mirrors the shape inject_curriculum expects: truck_id -> list of {id, role}
    assigned_crews: dict[str, list[dict]] = {}

    for assignment in assignments:
        truck = truck_map.get(str(assignment.truck_id))
        rows = (
            db.query(AssignmentMember, Employee)
            .join(Employee, AssignmentMember.employee_id == Employee.id)
            .filter(AssignmentMember.assignment_id == assignment.id)
            .all()
        )
        truck_crew: list[dict] = []
        for am, emp in rows:
            crew_by_assignment.append((am, emp, truck))
            all_employee_ids.append(str(emp.id))
            truck_crew.append({"id": emp.id, "role": am.role, "name": emp.name})
        assigned_crews[str(assignment.truck_id)] = truck_crew

    # Seed every employee as "pending" in Redis (idempotent)
    await seed_pending(str(dispatch_date), all_employee_ids)

    # Persist pending confirmation records to DB (idempotent — skip existing rows)
    existing_conf_ids = {
        str(r.employee_id)
        for r in db.query(DispatchConfirmation.employee_id)
            .filter(DispatchConfirmation.date == dispatch_date)
            .all()
    }
    for eid in all_employee_ids:
        if eid not in existing_conf_ids:
            db.add(DispatchConfirmation(
                employee_id=UUID(eid),
                date=dispatch_date,
                status="pending",
                source="discord_bot",
            ))

    # Seed in-app dispatch_assignment notifications (idempotent — skip if already exists)
    existing_notif_ids = {
        str(r.employee_id)
        for r in db.query(Notification.employee_id)
            .filter(
                Notification.type == "dispatch_assignment",
                Notification.dispatch_date == dispatch_date,
            )
            .all()
    }

    # Build trainer↔trainee pairing map for notification messages
    # trainer_for[trainee_id] = trainer_name, trainee_for[trainer_id] = trainee_name
    trainer_for: dict[str, str] = {}
    trainee_for: dict[str, str] = {}
    for truck_crew in assigned_crews.values():
        trainers = [m for m in truck_crew if m["role"] == "trainer"]
        trainees = [m for m in truck_crew if m["role"] == "trainee"]
        if trainers and trainees:
            # one trainee per truck — pair with the first trainer on that truck
            trainer = trainers[0]
            trainee = trainees[0]
            trainer_for[str(trainee["id"])] = trainer["name"]
            trainee_for[str(trainer["id"])] = trainee["name"]

    for am, emp, truck in crew_by_assignment:
        if str(emp.id) in existing_notif_ids:
            continue

        role = am.role
        truck_name = truck.name if truck else "a truck"
        if role == "driver":
            message = (
                f"You have been assigned to **{truck_name}** "
                f"for {dispatch_date}. Please confirm or decline your assignment. "
                f"Driver deadline: 08:20 AM."
            )
        elif role == "trainer":
            trainee_name = trainee_for.get(str(emp.id))
            if trainee_name:
                message = (
                    f"You are assigned to **{truck_name}** for {dispatch_date} "
                    f"and are paired with trainee **{trainee_name}**. "
                    f"Please confirm your attendance. Deadline: 09:00 AM."
                )
            else:
                message = (
                    f"You are assigned to **{truck_name}** for {dispatch_date}. "
                    f"No trainee is paired with you today. "
                    f"Please confirm your attendance. Deadline: 09:00 AM."
                )
        elif role == "trainee":
            trainer_name = trainer_for.get(str(emp.id))
            if trainer_name:
                message = (
                    f"You are assigned to **{truck_name}** for {dispatch_date} "
                    f"and are paired with trainer **{trainer_name}**. "
                    f"Please confirm your attendance. Deadline: 09:00 AM."
                )
            else:
                message = (
                    f"You are assigned to **{truck_name}** for {dispatch_date}. "
                    f"Please confirm your attendance. Deadline: 09:00 AM."
                )
        else:
            message = (
                f"You have a shift assignment for {dispatch_date}. "
                f"Please confirm your attendance. Deadline: 09:00 AM."
            )

        db.add(Notification(
            employee_id=emp.id,
            type="dispatch_assignment",
            message=message,
            dispatch_date=dispatch_date,
        ))

    db.commit()

    # Inject training curriculum for today's trainee-trainer pairings.
    # Runs here so manual-only dispatches (no auto-assign) still get training records.
    logger.info("inject_curriculum called date=%s truck_count=%d", dispatch_date, len(assigned_crews))
    cfg = get_company_config(db, caller.company_id)
    inject_curriculum(db, dispatch_date, assigned_crews, cfg=cfg)

    # Notify the bot via internal webhook
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{bot_url}/internal/publish",
                json={"date": str(dispatch_date), "company_id": str(caller.company_id)},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Bot webhook returned {resp.status}: {body}",
                    )
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the Discord bot: {e}",
        )

    logger.info("publish_dispatch complete date=%s employees_notified=%d company=%s", dispatch_date, len(all_employee_ids), caller.company_id)
    return {"status": "published", "date": str(dispatch_date), "employees_notified": len(all_employee_ids)}


def _reassign_trainee_on_trainer_decline(
    db: Session,
    trainer_id: UUID,
    dispatch_date: date,
) -> dict:
    """When a trainer declines, find their paired trainee and move them to the
    best available free trainer slot. Notifies all dispatch/admin employees.

    Returns a dict describing what happened:
      { "trainee_id": ..., "trainee_name": ..., "trainer_name": ...,
        "new_truck_name": ... | None, "new_trainer_name": ... | None,
        "placed": bool }
    """
    # Find the trainer's assignment for this date
    trainer_assignment = (
        db.query(AssignmentMember, TruckAssignment)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == trainer_id,
            TruckAssignment.date == dispatch_date,
        )
        .first()
    )
    logger.info("_reassign_trainee_on_trainer_decline started trainer_id=%s date=%s", trainer_id, dispatch_date)

    if not trainer_assignment:
        logger.warning("_reassign_trainee_on_trainer_decline: no assignment found trainer_id=%s date=%s", trainer_id, dispatch_date)
        return {}

    trainer_am, trainer_ta = trainer_assignment
    trainer_emp = db.query(Employee).filter(Employee.id == trainer_id).first()
    trainer_name = trainer_emp.name if trainer_emp else str(trainer_id)

    # Find this trainer's paired trainee on the same truck
    trainee_am = (
        db.query(AssignmentMember)
        .filter(
            AssignmentMember.assignment_id == trainer_ta.id,
            AssignmentMember.role == ROLE_TRAINEE,
        )
        .first()
    )
    if not trainee_am:
        # Trainer had no trainee — nothing to reassign
        return {}

    trainee_emp = db.query(Employee).filter(Employee.id == trainee_am.employee_id).first()
    trainee_name = trainee_emp.name if trainee_emp else str(trainee_am.employee_id)

    # Find the best destination: a truck where trainers > trainees (free slot)
    # Ranked by fewest trainees first so we fill the emptiest slot
    all_assignments = (
        db.query(TruckAssignment)
        .filter(TruckAssignment.date == dispatch_date)
        .all()
    )

    best_ta = None
    best_free_slots = 0
    for ta in all_assignments:
        if ta.id == trainer_ta.id:
            continue
        members = db.query(AssignmentMember).filter(AssignmentMember.assignment_id == ta.id).all()
        trainer_count = sum(1 for m in members if m.role == ROLE_TRAINER)
        trainee_count = sum(1 for m in members if m.role == ROLE_TRAINEE)
        free = trainer_count - trainee_count
        if free > best_free_slots:
            best_free_slots = free
            best_ta = ta

    # Move the trainee
    new_truck = db.query(Truck).filter(Truck.id == best_ta.truck_id).first() if best_ta else None
    new_truck_name = new_truck.name if new_truck else None
    placed = best_ta is not None

    if placed:
        trainee_am.assignment_id = best_ta.id

        # Find the trainer on the destination truck with the fewest trainees (most free)
        dest_members = db.query(AssignmentMember).filter(AssignmentMember.assignment_id == best_ta.id).all()
        dest_trainers = [m for m in dest_members if m.role == ROLE_TRAINER]
        dest_trainees_count = {t.employee_id: 0 for t in dest_trainers}
        for m in dest_members:
            if m.role == ROLE_TRAINEE and m.employee_id != trainee_am.employee_id:
                # attribute to whichever trainer has fewest — use first trainer as proxy
                if dest_trainers:
                    dest_trainees_count[dest_trainers[0].employee_id] += 1

        new_trainer_id = min(dest_trainees_count, key=dest_trainees_count.get) if dest_trainees_count else None
        new_trainer_emp = db.query(Employee).filter(Employee.id == new_trainer_id).first() if new_trainer_id else None
        new_trainer_name = (new_trainer_emp.name if new_trainer_emp else None) or "Unknown Trainer"

        # Update the TrainingRecord to reflect the new trainer
        training_record = (
            db.query(TrainingRecord)
            .filter(
                TrainingRecord.trainee_id == trainee_am.employee_id,
                TrainingRecord.record_date == dispatch_date,
            )
            .first()
        )
        if training_record and new_trainer_id:
            training_record.trainer_id = new_trainer_id
        elif training_record and not new_trainer_id:
            logger.warning(
                "_reassign_trainee_on_trainer_decline: no dest trainer found for trainee=%s on truck=%s date=%s",
                trainee_am.employee_id, best_ta.truck_id if best_ta else "?", dispatch_date,
            )
    else:
        new_trainer_name = None

    db.flush()

    # Notify all dispatch and admin employees
    dispatch_staff = (
        db.query(Employee)
        .filter(Employee.role.in_(list(OVERSIGHT_ROLES)), Employee.is_active == True)
        .all()
    )

    if placed:
        message = (
            f"⚠️ **Trainer declined — auto-reassignment:** "
            f"**{trainer_name}** declined their assignment for {dispatch_date}. "
            f"Their trainee **{trainee_name}** has been moved to **{new_truck_name}** "
            f"(paired with **{new_trainer_name}**). Please review."
        )
    else:
        message = (
            f"⚠️ **Trainer declined — no free slot:** "
            f"**{trainer_name}** declined their assignment for {dispatch_date}. "
            f"Their trainee **{trainee_name}** has no available trainer slot. "
            f"Manual reassignment required."
        )

    for staff in dispatch_staff:
        db.add(Notification(
            employee_id=staff.id,
            type="trainer_decline_reassignment",
            message=message,
            dispatch_date=dispatch_date,
        ))

    # Notify the trainee of their updated pairing
    if placed:
        trainee_message = (
            f"Your trainer for {dispatch_date} (**{trainer_name}**) is no longer available. "
            f"You have been reassigned to **{new_truck_name}** with trainer **{new_trainer_name}**. "
            f"Please check the dispatch board for details."
        )
    else:
        trainee_message = (
            f"Your trainer for {dispatch_date} (**{trainer_name}**) is no longer available. "
            f"No free trainer slot was found — dispatch has been notified and will reassign you manually."
        )
    db.add(Notification(
        employee_id=trainee_am.employee_id,
        type="trainer_decline_reassignment",
        message=trainee_message,
        dispatch_date=dispatch_date,
    ))

    db.commit()

    if placed:
        logger.info(
            "_reassign_trainee_on_trainer_decline placed trainee=%s (%s) to truck=%s trainer=%s date=%s",
            trainee_am.employee_id, trainee_name, new_truck_name, new_trainer_name, dispatch_date,
        )
    else:
        logger.warning(
            "_reassign_trainee_on_trainer_decline no free slot for trainee=%s (%s) date=%s",
            trainee_am.employee_id, trainee_name, dispatch_date,
        )

    return {
        "trainee_id": str(trainee_am.employee_id),
        "trainee_name": trainee_name,
        "trainer_name": trainer_name,
        "new_truck_name": new_truck_name,
        "new_trainer_name": new_trainer_name,
        "placed": placed,
    }


@router.post("/{dispatch_date}/confirmations", status_code=status.HTTP_200_OK)
async def record_confirmation(
    dispatch_date: date,
    payload: dict,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Record an employee's confirmation response.

    Called by the in-app buttons or Discord bot when an employee confirms/declines.

    Body: { "employee_id": "<uuid>", "status": "confirmed" | "declined" }

    Authorization:
    - Field staff (driver/walker/trainer/trainee) may only confirm their own assignment.
    - Dispatch, management, and admin may confirm on behalf of any employee.

    Write order: DB first (authoritative audit trail), then Redis (read cache).
    Redis failure is non-fatal — the dashboard will fall back to the DB state.
    """
    employee_id = payload.get("employee_id")
    conf_status = payload.get("status")

    if not employee_id or conf_status not in ("confirmed", "declined"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Body must contain employee_id and status ('confirmed' | 'declined').",
        )

    try:
        employee_uuid = UUID(employee_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"employee_id is not a valid UUID: {employee_id!r}",
        )

    # Field staff may only act on their own assignment.
    if caller.role not in OVERSIGHT_ROLES and str(caller.id) != str(employee_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only confirm or decline your own assignment.",
        )

    # Determine source: bot service account is role "dispatch" or "admin";
    # field staff confirming in-app gets labelled "app".
    source = "app" if caller.role not in OVERSIGHT_ROLES else "dispatch_override"

    # 1. Write to DB first — this is the authoritative audit trail.
    now = datetime.now(timezone.utc)
    row = db.query(DispatchConfirmation).filter(
        DispatchConfirmation.employee_id == employee_uuid,
        DispatchConfirmation.date == dispatch_date,
    ).first()
    if row:
        row.status = conf_status
        row.confirmed_at = now
        row.source = source
    else:
        db.add(DispatchConfirmation(
            employee_id=employee_uuid,
            date=dispatch_date,
            status=conf_status,
            confirmed_at=now,
            source=source,
        ))
    db.commit()

    # 2. Update Redis cache — non-fatal if Redis is unavailable.
    try:
        await set_confirmation(str(dispatch_date), str(employee_id), conf_status)
    except Exception:
        pass  # DB is authoritative; Redis is a read-cache only

    # 3. If a trainer declined, auto-reassign their trainee and alert dispatch.
    reassignment = {}
    if conf_status == "declined":
        emp = db.query(Employee).filter(Employee.id == employee_uuid).first()
        if emp and emp.role == ROLE_TRAINER:
            reassignment = _reassign_trainee_on_trainer_decline(
                db, employee_uuid, dispatch_date
            )

    return {
        "date": str(dispatch_date),
        "employee_id": employee_id,
        "status": conf_status,
        **({"reassignment": reassignment} if reassignment else {}),
    }


@router.get("/{dispatch_date}/my-confirmation", status_code=status.HTTP_200_OK)
def get_my_confirmation(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the caller's own confirmation status for a dispatch date.

    Returns { "date": "...", "status": "pending" | "confirmed" | "declined" | null }
    where null means no confirmation record exists for this employee on that date.
    """
    row = (
        db.query(DispatchConfirmation)
        .filter(
            DispatchConfirmation.employee_id == caller.id,
            DispatchConfirmation.date == dispatch_date,
        )
        .first()
    )
    return {
        "date": str(dispatch_date),
        "status": row.status if row else None,
        "confirmed_at": row.confirmed_at.isoformat() if (row and row.confirmed_at) else None,
    }


@router.get("/{dispatch_date}/confirmations", status_code=status.HTTP_200_OK)
async def get_confirmations(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all confirmation statuses for a dispatch date.

    Returns a dict of { employee_id: "pending" | "confirmed" | "declined" }.
    Redis is the read cache; falls back to DB if Redis is empty (e.g. after
    a restart) and re-seeds Redis from the DB result so subsequent reads are fast.
    """
    confirmations = await get_all_confirmations(str(dispatch_date))

    if not confirmations:
        # Redis is empty — read authoritative state from DB and re-seed Redis.
        rows = (
            db.query(DispatchConfirmation)
            .filter(DispatchConfirmation.date == dispatch_date)
            .all()
        )
        if rows:
            confirmations = {str(r.employee_id): r.status for r in rows}
            for employee_id, status_val in confirmations.items():
                try:
                    await set_confirmation(str(dispatch_date), employee_id, status_val)
                except Exception:
                    pass  # Redis unavailable — DB result still returned

    return {"date": str(dispatch_date), "confirmations": confirmations}


@router.get("/confirmations/history", status_code=status.HTTP_200_OK)
def get_confirmation_history(
    start_date: date = Query(..., description="Start of date range (inclusive)"),
    end_date:   date = Query(..., description="End of date range (inclusive)"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return confirmation records for a date range for analytics.

    Response: list of { employee_id, date, status, confirmed_at, source, created_at }
    """
    rows = (
        db.query(DispatchConfirmation)
        .filter(
            DispatchConfirmation.company_id == caller.company_id,
            DispatchConfirmation.date >= start_date,
            DispatchConfirmation.date <= end_date,
        )
        .order_by(DispatchConfirmation.date, DispatchConfirmation.employee_id)
        .all()
    )
    return [
        {
            "employee_id":  str(r.employee_id),
            "date":         str(r.date),
            "status":       r.status,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            "source":       r.source,
            "created_at":   r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/{dispatch_date}/finalize", status_code=status.HTTP_200_OK)
async def finalize_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Finalize the day's dispatch — post confirmed crews to Discord truck channels.

    Called manually by dispatch at ~09:10 AM after the confirmation window closes.
    Forwards the event to the bot, which:
      - Posts finalized crew embeds to each truck's Discord channel
      - Sets per-day channel permissions (confirmed crew + privileged roles only)
      - Posts the master driver list to #drivers-chat
    """
    assignments = db.query(TruckAssignment).filter(
        TruckAssignment.date == dispatch_date,
        TruckAssignment.company_id == caller.company_id,
    ).all()
    if not assignments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dispatch found for {dispatch_date}.",
        )

    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{bot_url}/internal/finalize",
                json={"date": str(dispatch_date), "company_id": str(caller.company_id)},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 202):
                    body = await resp.text()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Bot webhook returned {resp.status}: {body}",
                    )
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the Discord bot: {e}",
        )

    return {"status": "finalized", "date": str(dispatch_date)}


@router.delete("/{dispatch_date}", status_code=status.HTTP_204_NO_CONTENT)
def clear_daily_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Clear all truck assignments for a specific date.
    Returns 403 if the user tries to delete a dispatch for a past date.
    """
    if dispatch_date < date.today() and caller.role not in (ROLE_ADMIN,):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete assignment records for past days."
        )

    assignments = db.query(TruckAssignment).filter(
        TruckAssignment.date == dispatch_date,
        TruckAssignment.company_id == caller.company_id,
    ).all()
    for a in assignments:
        db.query(AssignmentMember).filter(AssignmentMember.assignment_id == a.id).delete()
        db.delete(a)
    db.commit()

    return


# ---------------------------------------------------------------------------
# Package Manifests
# ---------------------------------------------------------------------------

@router.post("/manifest", response_model=PackageManifestResponse, status_code=status.HTTP_201_CREATED)
def create_package_manifest(
    payload: PackageManifestCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Create a package manifest for a truck on a specific date. Dispatch/admin only.

    Records how many totes and OV packages were loaded onto the truck.
    One manifest per truck per date — use PATCH to update counts.
    """
    truck = db.query(Truck).filter(
        Truck.id == payload.truck_id,
        Truck.company_id == caller.company_id,
    ).first()
    if not truck:
        raise HTTPException(status_code=404, detail="Truck not found.")

    existing = db.query(PackageManifest).filter(
        PackageManifest.company_id == caller.company_id,
        PackageManifest.truck_id == payload.truck_id,
        PackageManifest.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Manifest already exists for this truck on this date. Use PATCH to update.",
        )

    row = PackageManifest(
        company_id=caller.company_id,
        truck_id=payload.truck_id,
        date=payload.date,
        tote_count=payload.tote_count,
        ov_count=payload.ov_count,
        notes=payload.notes,
        submitted_by=caller.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/manifest/{truck_id}", response_model=PackageManifestResponse)
def update_package_manifest(
    truck_id: UUID,
    payload: PackageManifestPatch,
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Update package counts on an existing manifest."""
    if target_date is None:
        target_date = date.today()

    row = db.query(PackageManifest).filter(
        PackageManifest.company_id == caller.company_id,
        PackageManifest.truck_id == truck_id,
        PackageManifest.date == target_date,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No manifest found for this truck on this date.")

    if payload.tote_count is not None:
        row.tote_count = payload.tote_count
    if payload.ov_count is not None:
        row.ov_count = payload.ov_count
    if payload.notes is not None:
        row.notes = payload.notes
    row.submitted_by = caller.id

    db.commit()
    db.refresh(row)
    return row


@router.get("/manifest/{truck_id}", response_model=PackageManifestResponse)
def get_package_manifest(
    truck_id: UUID,
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the manifest for a truck on a given date (default today)."""
    if target_date is None:
        target_date = date.today()

    row = db.query(PackageManifest).filter(
        PackageManifest.company_id == caller.company_id,
        PackageManifest.truck_id == truck_id,
        PackageManifest.date == target_date,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No manifest found.")
    return row


@router.get("/manifests/summary")
def get_manifests_summary(
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all manifests for a date with truck names and totals. Dispatch/admin only."""
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(PackageManifest)
        .filter(
            PackageManifest.company_id == caller.company_id,
            PackageManifest.date == target_date,
        )
        .order_by(PackageManifest.submitted_at.asc())
        .all()
    )

    truck_ids = {r.truck_id for r in rows}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    return {
        "date": target_date.isoformat(),
        "total_totes": sum(r.tote_count for r in rows),
        "total_ov": sum(r.ov_count for r in rows),
        "trucks": [
            {
                "truck_id": str(r.truck_id),
                "truck_name": truck_map[r.truck_id].name if r.truck_id in truck_map else "Unknown",
                "tote_count": r.tote_count,
                "ov_count": r.ov_count,
                "notes": r.notes,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in rows
        ],
    }
