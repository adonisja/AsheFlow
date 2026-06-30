from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.schemas.truck_assignment import TruckAssignmentCreate, TruckAssignmentUpdate, TruckAssignmentResponse

router = APIRouter(prefix="/assignments", tags=["assignments"])

allow_dispatch_mgmt = RoleChecker(["dispatch", "management", "admin"])
allow_any_auth      = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.post("/", response_model=TruckAssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(assignment: TruckAssignmentCreate, db: Session = Depends(get_db), _: dict = Depends(allow_dispatch_mgmt)):
    """Create a new truck assignment record.

    Args:
        assignment: Validated truck assignment creation payload.
        db: Database session.

    Returns:
        The newly created TruckAssignment record.
    """
    db_assignment = TruckAssignment(**assignment.model_dump())
    db.add(db_assignment)
    db.commit()
    db.refresh(db_assignment)
    return db_assignment


@router.get("/", response_model=list[TruckAssignmentResponse])
def get_assignments(db: Session = Depends(get_db), _: dict = Depends(allow_any_auth), caller: Employee = Depends(get_caller_employee)):
    """Return all truck assignments for the caller's company, including resolved truck name."""
    rows = (
        db.query(TruckAssignment, Truck.name.label("truck_name"))
        .join(Truck, Truck.id == TruckAssignment.truck_id)
        .filter(TruckAssignment.company_id == caller.company_id)
        .all()
    )
    return [
        TruckAssignmentResponse(
            id         = ta.id,
            truck_id   = ta.truck_id,
            truck_name = name or "",
            date       = ta.date,
            status     = ta.status,
        )
        for ta, name in rows
    ]


@router.get("/{assignment_id}", response_model=TruckAssignmentResponse)
def get_assignment(assignment_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth), caller: Employee = Depends(get_caller_employee)):
    """Fetch a single truck assignment by ID."""
    assignment = db.query(TruckAssignment).filter(
        TruckAssignment.id == assignment_id,
        TruckAssignment.company_id == caller.company_id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    return assignment


@router.put("/{assignment_id}", response_model=TruckAssignmentResponse)
def update_assignment(assignment_id: UUID, assignment: TruckAssignmentUpdate, db: Session = Depends(get_db), _: dict = Depends(allow_dispatch_mgmt), caller: Employee = Depends(get_caller_employee)):
    """Update an existing truck assignment's fields."""
    db_assignment = db.query(TruckAssignment).filter(
        TruckAssignment.id == assignment_id,
        TruckAssignment.company_id == caller.company_id,
    ).first()
    if not db_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    for key, value in assignment.model_dump(exclude_unset=True).items():
        setattr(db_assignment, key, value)

    db.commit()
    db.refresh(db_assignment)
    return db_assignment
