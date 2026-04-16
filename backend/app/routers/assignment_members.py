from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.schemas.assignment_member import AssignmentMemberCreate, AssignmentMemberResponse
from app.services.previous_assignment import check_consecutive_assignment
from app.services.check_ban import check_ban_relationship

router = APIRouter(prefix="/assignment-members", tags=["assignment-members"])

allow_dispatch_mgmt = RoleChecker(["dispatch", "management", "admin"])
allow_any_auth      = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.post("/", response_model=AssignmentMemberResponse, status_code=status.HTTP_201_CREATED)
def create_assignment_member(
    assignment_member: AssignmentMemberCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch_mgmt),
):
    """Add an employee to an existing truck assignment after running constraint checks.

    Verifies that the assignment exists, the employee was not on the same truck
    the previous day, and the employee has no ban relationship with any current
    member of the assignment.

    Args:
        assignment_member: Validated payload containing assignment_id, employee_id,
            and role.
        db: Database session.

    Returns:
        The newly created AssignmentMember record.

    Raises:
        HTTPException(404): If the assignment does not exist.
        HTTPException(409): If a consecutive-truck or ban-list conflict is detected.
    """
    # Step 1 — verify the assignment exists and get truck + date
    assignment = db.query(TruckAssignment).filter(
        TruckAssignment.id == assignment_member.assignment_id
    ).first()

    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    # Step 2 — consecutive truck check
    if check_consecutive_assignment(assignment_member.employee_id, assignment.truck_id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee was on this truck yesterday"
        )

    # Step 3 — ban list check against all existing members on this assignment
    existing_members = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_member.assignment_id
    ).all()

    for existing in existing_members:
        if check_ban_relationship(assignment_member.employee_id, existing.employee_id, db):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Employee is banned from someone already on this assignment"
            )

    # Step 4 — all checks passed, insert the member
    db_member = AssignmentMember(**assignment_member.model_dump())
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    return db_member


@router.get("/{assignment_id}", response_model=list[AssignmentMemberResponse])
def get_assignment_members(assignment_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Return all members belonging to a specific truck assignment.

    Args:
        assignment_id: UUID of the truck assignment.
        db: Database session.

    Returns:
        List of AssignmentMember records for the given assignment.
    """
    return db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_id
    ).all()


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment_member(member_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_dispatch_mgmt)):
    """Remove an employee from a truck assignment.

    Args:
        member_id: UUID of the AssignmentMember row to delete.
        db: Database session.

    Raises:
        HTTPException(404): If no member with the given ID exists.
    """
    member = db.query(AssignmentMember).filter(AssignmentMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    db.delete(member)
    db.commit()
