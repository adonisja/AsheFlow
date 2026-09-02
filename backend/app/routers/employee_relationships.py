from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_


from app.database import get_db
from app.services.audit import write_audit
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.services.seat_crew_pins import nullify_pins_for_ban
from app.schemas.employee_relationship import EmployeeRelationshipResponse, EmployeeRelationshipCreate


router = APIRouter(prefix="/employee-relationships", tags=["employee-relationships"])

allow_field_staff = RoleChecker(["captain", "driver", "walker", "trainer"])
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
    # How many favs each role may hold, per target role (ADR-353, superseding the
    # ADR-256 table).
    #
    # A missing key means ZERO, not unlimited — the lookup below defaults to 0.
    # The two remaining gaps are deliberate and are NOT oversights:
    #   driver→driver, captain→captain: one per truck, so the preference is
    #     meaningless (ADR-256's reasoning, unchanged).
    #   walker→trainer: the two roles rarely affect each other's day, and the pair
    #     is not needed by the tridirectional trio (ADR-353 D2).
    #
    # NAMING THE GAPS MATTERS. ADR-256 removed trainer→walker for a defensible
    # reason and did not notice that perform_tridirectional_check required it —
    # the bonus became unreachable and stayed that way, silently. A cap of 0 is a
    # decision about every consumer of that pair, not just about the UI.
    #
    # Existing rows above a cap are not deleted; caps gate NEW rows only.
    FAV_LIMITS = {
        "driver":  {"driver": 0, "captain": 2, "trainer": 1, "walker": 2},
        "captain": {"driver": 2, "captain": 0, "trainer": 1, "walker": 2},
        "trainer": {"driver": 1, "captain": 1, "walker": 1},
        "walker":  {"driver": 2, "captain": 2, "walker": 1},
    }

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

        # Look up the cap for this initiator-role → target-role pair. `.get(..., 0)`
        # on BOTH levels: a missing pair means "not allowed", not a KeyError 500.
        # Direct subscripting was safe only while every role appeared in every row;
        # ADR-256 removed trainer→walker and walker→trainer, so gaps are now normal.
        # An unknown role (dispatch, field_supervisor, driver_trainee) also lands
        # here and is correctly refused rather than crashing.
        cap = FAV_LIMITS.get(db_employee.role, {}).get(db_target.role, 0)
        if existing_count >= cap:
            if cap == 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"A {db_employee.role} cannot add a {db_target.role} as a favourite."
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Employee already has {cap} {db_target.role}(s) in their "
                    f"{employee_relationship.relationship_type} list"
                ),
            )

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
    db.flush()

    # ADR-357 D4 — a ban between two pinned crew members nullifies their pin.
    # Done at CREATION rather than at dispatch time so the dispatcher learns now,
    # instead of discovering at 4am that a crew silently stopped being a crew.
    if employee_relationship.relationship_type == "ban":
        nullified = nullify_pins_for_ban(
            db,
            caller.company_id,
            db_employee.id,
            db_target.id,
        )
        for pin in nullified:
            write_audit(
                db=db,
                company_id=caller.company_id,
                actor_id=caller.id,
                action_type="crew_pin.auto_deactivated",
                target_table="crew_pins",
                target_id=str(pin.id),
                detail={
                    "reason": "ban_between_members",
                    "employee_id": str(db_employee.id),
                    "target_employee_id": str(db_target.id),
                },
            )

    # The delete side is audited (ADR-132 DP-3/DP-5) and the clear side now is
    # too (D13) — create was the remaining hole, so a relationship could appear
    # with no record and be removed with one.
    write_audit(
        db,
        action_type="employee_relationship.create",
        target_table="employee_relationships",
        target_id=str(db_relationship.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"employee_id": str(db_relationship.employee_id),
               "target_employee_id": str(db_relationship.target_employee_id),
               "relationship_type": db_relationship.relationship_type},
    )
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

    # Snapshot before deleting: ADR-132 DP-3/DP-5 audited the sibling
    # `delete_employee_relationships` for exactly this (GDPR Art. 17); this
    # bulk-clear path was missed and deleted the same personal data silently.
    doomed = db.query(EmployeeRelationship).filter(
        EmployeeRelationship.employee_id == employee_id,
        EmployeeRelationship.company_id == caller.company_id,
    ).all()
    before = {
        "count": len(doomed),
        "relationship_ids": [str(r.id) for r in doomed],
    }
    for r in doomed:
        db.delete(r)

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="employee_relationship.clear",
        target_table="employee_relationships",
        target_id=str(employee_id),
        before=before,
    )
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

    write_audit(
        db,
        action_type="employee_relationship.deleted",
        target_table="employee_relationships",
        target_id=str(relationship.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        before={
            "employee_id": str(relationship.employee_id),
            "related_employee_id": str(relationship.related_employee_id),
            "relationship_type": relationship.relationship_type,
        },
        after=None,
    )
    db.delete(relationship)
    db.commit()