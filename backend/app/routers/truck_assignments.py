from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.truck_assignment import TruckAssignment
from app.schemas.truck_assignment import TruckAssignmentCreate, TruckAssignmentUpdate, TruckAssignmentResponse

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("/", response_model=TruckAssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(assignment: TruckAssignmentCreate, db: Session = Depends(get_db)):
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
def get_assignments(db: Session = Depends(get_db)):
    """Return all truck assignments.

    Args:
        db: Database session.

    Returns:
        List of all TruckAssignment records.
    """
    return db.query(TruckAssignment).all()


@router.get("/{assignment_id}", response_model=TruckAssignmentResponse)
def get_assignment(assignment_id: UUID, db: Session = Depends(get_db)):
    """Fetch a single truck assignment by ID.

    Args:
        assignment_id: UUID of the assignment to retrieve.
        db: Database session.

    Returns:
        The matching TruckAssignment record.

    Raises:
        HTTPException(404): If no assignment with the given ID exists.
    """
    assignment = db.query(TruckAssignment).filter(TruckAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    return assignment


@router.put("/{assignment_id}", response_model=TruckAssignmentResponse)
def update_assignment(assignment_id: UUID, assignment: TruckAssignmentUpdate, db: Session = Depends(get_db)):
    """Update an existing truck assignment's fields.

    Args:
        assignment_id: UUID of the assignment to update.
        assignment: Partial update payload; only provided fields are applied.
        db: Database session.

    Returns:
        The updated TruckAssignment record.

    Raises:
        HTTPException(404): If no assignment with the given ID exists.
    """
    db_assignment = db.query(TruckAssignment).filter(TruckAssignment.id == assignment_id).first()
    if not db_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    for key, value in assignment.model_dump(exclude_unset=True).items():
        setattr(db_assignment, key, value)

    db.commit()
    db.refresh(db_assignment)
    return db_assignment
