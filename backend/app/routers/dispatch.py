from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_current_user, RoleChecker
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck import Truck
from app.schemas.dispatch import ManualAssignmentCreate, ManualAssignmentUpdate, DispatchConfig
from app.services.run_dispatch import run_dispatch
from app.services.available_pool import get_unavailable_staff

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# Dispatch operations are limited to dispatch role and admin only.
# Management (supervisory) accesses fleet data via reporting endpoints, not the operational dispatch tool.
allow_dispatch_mgmt = RoleChecker(["dispatch", "admin"])

@router.get("/unavailable-staff/{dispatch_date}", status_code=status.HTTP_200_OK)
def get_unavailable_staff_for_date(
    dispatch_date: date,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt),
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
        "unavailable_staff": get_unavailable_staff(db, dispatch_date, roles=roles),
    }


@router.get("/{dispatch_date}", status_code=status.HTTP_200_OK)
def get_daily_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
):
    """Retrieve all truck assignments and their crews for a specific date."""
    
    assignments = db.query(TruckAssignment).filter(TruckAssignment.date == dispatch_date).all()
    
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
                "role": am.role
            })
            
        assigned_crews[str(assignment.truck_id)] = crew_list
        
    return {
        "date": dispatch_date,
        "assigned_crews": assigned_crews,
        "warnings": []
    }

@router.post("/", status_code=status.HTTP_201_CREATED)
def trigger_dispatch(
    config: Optional[DispatchConfig] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
):
    """Run today's dispatch if one does not already exist."""
    
    target_date = config.date if config and config.date else date.today()

    # prevent double-dispatch — if any TruckAssignment row exists for today, reject immediately
    existing = db.query(TruckAssignment).filter(TruckAssignment.date == target_date).first()
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
            
        assigned_crews, warnings = run_dispatch(db, target_date, total_employees, total_trucks)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
def manual_assignment(
    assignment_in: ManualAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
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
    # Verify employee exists
    employee = db.query(Employee).filter(Employee.id == assignment_in.employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {assignment_in.employee_id} not found"
        )
    
    # Verify truck exists
    truck = db.query(Truck).filter(Truck.id == assignment_in.truck_id).first()
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
            truck_id=assignment_in.truck_id,
            date=assignment_in.date
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
    if assignment_in.role == "trainee":
        # Check if the truck already has a trainee
        existing_trainee_assignment = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == truck_assignment.id,
            AssignmentMember.role == "trainee"
        ).first()

        if existing_trainee_assignment:
            bumped_trainee_id = existing_trainee_assignment.employee_id
            db.delete(existing_trainee_assignment)
            db.flush()

            # Find another truck with a trainer but NO trainee
            # First get all trucks for this date
            all_truck_assignments = db.query(TruckAssignment).filter(
                TruckAssignment.date == assignment_in.date
            ).all()

            fallback_assignment_id = None
            for ta in all_truck_assignments:
                if ta.id == truck_assignment.id:
                    continue
                
                members = db.query(AssignmentMember).filter(AssignmentMember.assignment_id == ta.id).all()
                has_trainer = any(m.role == "trainer" for m in members)
                has_trainee = any(m.role == "trainee" for m in members)

                if has_trainer and not has_trainee:
                    fallback_assignment_id = ta.id
                    break
            
            # If no truck with trainer and without trainee, just find any truck without a trainee, or just any truck.
            if not fallback_assignment_id:
                for ta in all_truck_assignments:
                    if ta.id == truck_assignment.id:
                        continue
                    members = db.query(AssignmentMember).filter(AssignmentMember.assignment_id == ta.id).all()
                    has_trainee = any(m.role == "trainee" for m in members)
                    if not has_trainee:
                        fallback_assignment_id = ta.id
                        break
            
            if fallback_assignment_id:
                bumped_member = AssignmentMember(
                    assignment_id=fallback_assignment_id,
                    employee_id=bumped_trainee_id,
                    role="trainee"
                )
                db.add(bumped_member)
            else:
                # If nowhere to put them, maybe convert to walker on some truck or just leave unassigned?
                # We will just unassign them if there's no room, which is handled since we deleted them.
                pass


    new_member = AssignmentMember(
        assignment_id=truck_assignment.id,
        employee_id=assignment_in.employee_id,
        role=assignment_in.role
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    
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
    employee_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
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
        TruckAssignment.date == date
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
    current_user: dict = Depends(allow_dispatch_mgmt)
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
        TruckAssignment.date == assignment_in.date
    ).first()
    
    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {assignment_in.employee_id} is not scheduled on {assignment_in.date}."
        )

    # Step 2: Guarantee the target truck exists
    destination_truck = db.query(Truck).filter(Truck.id == assignment_in.new_truck_id).first()
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
            truck_id=assignment_in.new_truck_id,
            date=assignment_in.date
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


@router.delete("/{dispatch_date}", status_code=status.HTTP_204_NO_CONTENT)
def clear_daily_dispatch(
    dispatch_date: date,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
):
    """Clear all truck assignments for a specific date.
    Returns 403 if the user tries to delete a dispatch for a past date.
    """
    if dispatch_date < date.today() and "admin" not in current_user.get("cognito_groups", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete assignment records for past days."
        )

    assignments = db.query(TruckAssignment).filter(TruckAssignment.date == dispatch_date).all()
    for a in assignments:
        db.query(AssignmentMember).filter(AssignmentMember.assignment_id == a.id).delete()
        db.delete(a)
    db.commit()
    
    return
