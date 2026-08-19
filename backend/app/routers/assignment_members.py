from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.services.constants import ROUTE_LEAD_ROLES
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route, RouteParticipant
from app.models.delivery_stop import DeliveryStop
from app.schemas.assignment_member import (
    AssignmentMemberCreate,
    AssignmentMemberResponse,
    AssignmentMemberStatusUpdate,
    CrewAvailabilityEntry,
    CrewAvailabilityResponse,
)
from app.services.previous_assignment import check_consecutive_assignment
from app.services.check_ban import check_ban_relationship
from app.models.shift_roll_call import ShiftRollCall
from app.services.crew_availability import (
    MemberProgress,
    derive_availability,
    present_from_roll_call,
    DEFAULT_COMPLETION_THRESHOLD,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/assignment-members", tags=["assignment-members"])

allow_dispatch_mgmt = RoleChecker(["dispatch", "management", "admin"])
# ADR-256 D13: named for scope granted. Trainer removed (D5); captain + field_supervisor added.
allow_route_lead    = RoleChecker(list(ROUTE_LEAD_ROLES))
allow_any_auth      = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.post("/", response_model=AssignmentMemberResponse, status_code=status.HTTP_201_CREATED)
def create_assignment_member(
    assignment_member: AssignmentMemberCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
    db: Session = Depends(get_db),
):
    """Add an employee to an existing truck assignment after running constraint checks."""
    assignment = db.query(TruckAssignment).filter(
        TruckAssignment.id == assignment_member.assignment_id,
        TruckAssignment.company_id == caller.company_id,
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
def get_assignment_members(
    assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
    db: Session = Depends(get_db),
):
    """Return all members belonging to a specific truck assignment."""
    return (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.assignment_id == assignment_id,
            TruckAssignment.company_id == caller.company_id,
        )
        .all()
    )


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment_member(
    member_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
    db: Session = Depends(get_db),
):
    """Remove an employee from a truck assignment."""
    member = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(AssignmentMember.id == member_id, TruckAssignment.company_id == caller.company_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="assignment_member.remove",
        target_table="assignment_members",
        target_id=str(member.id),
        before={"assignment_id": str(member.assignment_id),
                "employee_id": str(member.employee_id),
                "role": member.role},
    )
    db.delete(member)
    db.commit()


@router.patch("/{member_id}/status", response_model=AssignmentMemberResponse)
def update_member_status(
    member_id: UUID,
    body: AssignmentMemberStatusUpdate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_route_lead),
    db: Session = Depends(get_db),
):
    """Mark a crew member departed or transferred (ADR-197 Phase 0b).

    Unlike DELETE (which erases the row and its crew history), this is a SOFT
    state change that preserves the record — F5's live-crew count and analytics
    need to know the person WAS on the truck and when they left. Dispatch/captain
    only. Idempotency: a member already in a terminal (non-active) status → 409.
    """
    member = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(AssignmentMember.id == member_id, TruckAssignment.company_id == caller.company_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Member is already {member.status}.",
        )

    member.status      = body.status
    member.departed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db=db, company_id=str(caller.company_id), actor_id=str(caller.id),
        action_type="assignment_member.status_change",
        target_table="assignment_members", target_id=str(member.id),
        detail={"status": body.status, "reason": body.reason, "employee_id": str(member.employee_id)},
    )
    db.commit()
    db.refresh(member)
    return AssignmentMemberResponse.model_validate(member, from_attributes=True)


@router.get("/{assignment_id}/availability", response_model=CrewAvailabilityResponse)
def get_crew_availability(
    assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_route_lead),
    db: Session = Depends(get_db),
):
    """Derived crew availability for a truck (ADR-197 Phase 0b).

    Combines membership status with route-execution progress so F5 route-creation
    knows how many walkers can take a NEW route this wave (walker count is a
    CEILING on routes, not a target). A walker >65% through their route counts as
    'returning' (a route can wait for them); ≤65% is 'on_route_early' (not this
    wave). Availability = completed DeliveryStops / total stops on their route.
    """
    ta = db.query(TruckAssignment).filter(
        TruckAssignment.id == assignment_id,
        TruckAssignment.company_id == caller.company_id,
    ).first()
    if not ta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    members = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_id,
        AssignmentMember.company_id == caller.company_id,
    ).all()

    # Employee names in one query
    emp_ids = [m.employee_id for m in members]
    names = {
        e.id: e.name
        for e in db.query(Employee).filter(
            Employee.id.in_(emp_ids), Employee.company_id == caller.company_id
        ).all()
    } if emp_ids else {}

    # Roll-call presence for the assignment's date (ADR-200). Without this every
    # member defaults to present=True → 'available', so the crew roster shows the
    # whole crew Available before anyone has been marked in. None (no record) →
    # 'not_arrived'; this also correctly holds un-arrived members out of the
    # available-for-route count until roll call marks them in.
    roll_calls = {
        rc.employee_id: rc.status
        for rc in db.query(ShiftRollCall).filter(
            ShiftRollCall.employee_id.in_(emp_ids),
            ShiftRollCall.date == ta.date,
            ShiftRollCall.company_id == caller.company_id,
        ).all()
    } if emp_ids else {}

    # Each active member's current (assigned/in_progress, not returned) route +
    # its completion %. ADR-212: a member is "on" a route if they are a
    # participant (executor or supervisor).
    progress: list[MemberProgress] = []
    for m in members:
        has_route = False
        pct: float | None = None
        if m.status == "active":
            member_route_ids = (
                db.query(RouteParticipant.route_id)
                .filter(
                    RouteParticipant.employee_id == m.employee_id,
                    RouteParticipant.company_id == caller.company_id,
                )
            )
            route = db.query(Route).filter(
                Route.company_id == caller.company_id,
                Route.truck_assignment_id == assignment_id,
                Route.returned_at.is_(None),
                Route.status.in_(("assigned", "in_progress")),
                Route.id.in_(member_route_ids),
            ).first()
            if route is not None:
                has_route = True
                total = db.query(DeliveryStop).filter(
                    DeliveryStop.route_id == route.id,
                    DeliveryStop.company_id == caller.company_id,
                ).count()
                done = db.query(DeliveryStop).filter(
                    DeliveryStop.route_id == route.id,
                    DeliveryStop.company_id == caller.company_id,
                    DeliveryStop.status == "completed",
                ).count()
                pct = (done / total) if total else 0.0
        progress.append(MemberProgress(
            employee_id=m.employee_id, name=names.get(m.employee_id), role=m.role,
            membership_status=m.status, has_active_route=has_route, route_completion_pct=pct,
            present=present_from_roll_call(roll_calls.get(m.employee_id)),
        ))

    entries, active_crew, available = derive_availability(progress)
    return CrewAvailabilityResponse(
        entries=[
            CrewAvailabilityEntry(
                employee_id=e.employee_id, name=e.name, role=e.role,
                membership_status=e.membership_status, availability=e.availability,
                route_completion_pct=e.route_completion_pct,
            ) for e in entries
        ],
        active_crew=active_crew,
        available_for_route=available,
        completion_threshold=DEFAULT_COMPLETION_THRESHOLD,
    )
