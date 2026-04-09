from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_current_user, RoleChecker
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck import Truck
from app.schemas.dispatch import ManualAssignmentCreate, ManualAssignmentUpdate
from app.services.run_dispatch import run_dispatch
from app.schemas.dispatch import ManualAssignmentUpdate


router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# Create a dependency instance allowing only dispatch and management roles
allow_dispatch_mgmt = RoleChecker(["dispatch", "management", "admin"])

@router.post("/", status_code=status.HTTP_201_CREATED)
def trigger_dispatch(
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_dispatch_mgmt)
    ):
    """Run today's dispatch if one does not already exist.

    Args:
        db: Database session injected by FastAPI.
        current_user: Authenticated user dict injected by FastAPI.

    Returns:
        A dict containing ``date``, ``assigned_crews`` (truck UUID → crew list),
        and ``warnings`` (list of staffing or ban-conflict warning dicts).

    Raises:
        HTTPException(409): If a dispatch already exists for today.
        HTTPException(400): If there are insufficient drivers to run dispatch.
    """
    today = date.today()

    # prevent double-dispatch — if any TruckAssignment row exists for today, reject immediately
    existing = db.query(TruckAssignment).filter(TruckAssignment.date == today).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dispatch already exists for {today}"
        )

    # ValueError is raised by run_dispatch when there aren't enough drivers to cover all trucks
    try:
        assigned_crews, warnings = run_dispatch(db, today)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # warnings are a mix of two shapes: staffing dicts have a "type" key, ban-conflict dicts have UUIDs —
    # serialize UUID fields to strings so JSON serialization doesn't fail
    serialized_warnings = []
    for w in warnings:
        if "type" in w:
            # staffing warnings are already JSON-safe strings
            serialized_warnings.append(w)
        else:
            # ban-conflict warnings contain UUID objects that must be cast to str
            serialized_warnings.append({
                "employee_id": str(w["employee_id"]),
                "banned_by": [str(b) for b in w["banned_by"]]
            })

    return {
        "date": today,
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

