from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_


from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.schemas.employee_relationship import EmployeeRelationshipResponse, EmployeeRelationshipCreate


router = APIRouter(prefix="/employee-relationships", tags=["employee-relationships"])

allow_field_staff = RoleChecker(["driver", "walker", "trainer"])
allow_admin       = RoleChecker(["admin"])

@router.post("/", response_model=EmployeeRelationshipResponse, status_code=status.HTTP_201_CREATED)
def create_employee_relationship(
    employee_relationship: EmployeeRelationshipCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_field_staff),
    caller: Employee = Depends(get_caller_employee),
):
    """Create a fav or ban relationship between two employees, enforcing role-based limits.

    For ``fav`` relationships, enforces per-role caps defined by FAV_LIMITS.
    For ``ban`` relationships, limits each employee to two active bans.  Prevents
    self-relationships and duplicate entries.

    Args:
        employee_relationship: Validated payload with employee_id, target_employee_id,
            and relationship_type.
        db: Database session.

    Returns:
        The newly created EmployeeRelationship record.

    Raises:
        HTTPException(404): If either employee does not exist.
        HTTPException(400): If an employee attempts to relate to themselves.
        HTTPException(409): If a limit is exceeded or the relationship already exists.
    """
    # defines how many favs each role can have per target role — drivers can't fav other drivers,
    # but can fav 1 trainer and 2 walkers; trainers and walkers are symmetric
    FAV_LIMITS = {"driver": {"driver": 0, "trainer": 1, "walker": 2}, "trainer": {"driver": 1, "trainer": 1, "walker": 2}, "walker": {"driver": 1, "trainer": 1, "walker": 2}}

    # Ownership — field staff can only create relationships for themselves
    if caller.id != employee_relationship.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only create relationships for yourself.",
        )

    db_employee = db.query(Employee).filter(
        Employee.id == employee_relationship.employee_id,
        Employee.company_id == caller.company_id,
    ).first()

    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_target = db.query(Employee).filter(
        Employee.id == employee_relationship.target_employee_id,
        Employee.company_id == caller.company_id,
    ).first()

    if not db_target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target employee not found")

    # catch self-referential relationships before hitting the DB limit checks
    if db_employee.id == db_target.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee cannot ban themselves")

    if employee_relationship.relationship_type == "fav":
        # join to Employee so we can filter by the target's role — the limit is per-role, not total
        existing_count = db.query(EmployeeRelationship).join(
            Employee, EmployeeRelationship.target_employee_id == Employee.id).filter(
                and_(EmployeeRelationship.employee_id == db_employee.id,
                    EmployeeRelationship.company_id == caller.company_id,
                    Employee.role == db_target.role,
                    EmployeeRelationship.relationship_type == employee_relationship.relationship_type)).count()

        # look up the cap for this specific initiator-role → target-role pair
        if existing_count >= FAV_LIMITS[db_employee.role][db_target.role]:
            raise HTTPException(status_code=409, detail=f"Employee already has {FAV_LIMITS[db_employee.role][db_target.role]} members in {employee_relationship.relationship_type} list")

    else:
        # ban limit is global (not role-segmented) — each employee may only ban 2 people total
        ban_count = db.query(EmployeeRelationship).filter(
            EmployeeRelationship.employee_id == db_employee.id,
            EmployeeRelationship.company_id == caller.company_id,
            EmployeeRelationship.relationship_type == "ban"
        ).count()

        if ban_count >= 2:
            raise HTTPException(status_code=409, detail="Employee already has 2 bans")

    # guard against exact duplicates after passing all limit checks
    existing = db.query(EmployeeRelationship).filter(
        EmployeeRelationship.employee_id == employee_relationship.employee_id,
        EmployeeRelationship.company_id == caller.company_id,
        EmployeeRelationship.target_employee_id == employee_relationship.target_employee_id,
        EmployeeRelationship.relationship_type == employee_relationship.relationship_type
    ).first()

    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Relationship already exists")

    db_relationship = EmployeeRelationship(
        **employee_relationship.model_dump(),
        company_id=caller.company_id,
    )
    db.add(db_relationship)
    db.commit()
    # refresh to populate server-generated fields (e.g. id, created_at) before returning
    db.refresh(db_relationship)
    return db_relationship

@router.get("/", response_model=list[EmployeeRelationshipResponse])
def get_all_employee_relationships(db: Session = Depends(get_db), _: dict = Depends(allow_admin), caller: Employee = Depends(get_caller_employee)):
    """Return all employee relationship records. Admin only — used for aggregate analytics.

    Dispatch and management must never access individual-level fav/ban data directly.
    The dispatch service reads relationships internally via service functions, not this endpoint.
    """
    return db.query(EmployeeRelationship).filter(
        EmployeeRelationship.company_id == caller.company_id,
    ).all()


@router.get("/{employee_id}", response_model=list[EmployeeRelationshipResponse])
def get_employee_relationships(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all relationships where the given employee is the source.

    Each employee can only read their own list. Admin may read any employee's list
    (supports the emulation/view-as feature). Management and dispatch cannot view
    individual fav/ban lists — dispatch reads relationship data internally via service
    functions during assignment computation, not through this endpoint.
    """
    if caller.role != "admin" and caller.id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own relationships.",
        )
    return db.query(EmployeeRelationship).filter(
        EmployeeRelationship.employee_id == employee_id,
        EmployeeRelationship.company_id == caller.company_id,
    ).all()

@router.delete("/employee/{employee_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def clear_employee_relationships(employee_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_admin), caller: Employee = Depends(get_caller_employee)):
    """Delete all relationships where the given employee is the source.

    Args:
        employee_id: UUID of the employee whose relationships to clear.
        db: Database session.

    Raises:
        HTTPException(404): If the employee does not exist.
    """
    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()

    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db.query(EmployeeRelationship).filter(
        EmployeeRelationship.employee_id == employee_id,
        EmployeeRelationship.company_id == caller.company_id,
    ).delete()
    db.commit()

@router.delete("/{employee_relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee_relationships(
    employee_relationship_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Delete a single employee relationship record by its ID.

    Field staff can only delete their own relationships. Management/admin can delete any.
    """
    relationship = db.query(EmployeeRelationship).filter(
        EmployeeRelationship.id == employee_relationship_id,
        EmployeeRelationship.company_id == caller.company_id,
    ).first()
    if not relationship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")

    if caller.role != "admin" and caller.id != relationship.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own relationships.",
        )

    db.delete(relationship)
    db.commit()