"""Crew Status page (ADR-197 Phase B).

GET /crew-status/{date} — a fleet-aware, enriched crew view:
  - availability (ADR-197 Phase 0b): membership status + route-execution progress
  - trip count (ADR-199 D3): completed-and-returned runs today
  - pairing (ADR-199): trainer↔trainee, with an orphaned-trainee flag that drives
    the Phase B dispatch reassignment entry point

Scope by role:
  - dispatch / management / admin: every truck on the date
  - driver / trainer: only their own truck

Read-only. The depart/status action stays on /assignment-members/{id}/status.
Distinct from /assignment-members/{assignment_id}/availability, which F5 route-
creation consumes as a route ceiling — that hot path is intentionally NOT touched.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck_assignment import TruckAssignment
from app.models.truck import Truck
from app.models.walker_route import Route
from app.models.delivery_stop import DeliveryStop
from app.models.shift_roll_call import ShiftRollCall
from app.schemas.assignment_member import (
    CrewStatusMember, CrewStatusTruck, CrewStatusResponse,
)
from app.services.crew_availability import (
    MemberProgress, derive_availability, classify_member, DEFAULT_COMPLETION_THRESHOLD,
)
from app.services.constants import ROLE_TRAINEE, OVERSIGHT_ROLES

router = APIRouter(prefix="/crew-status", tags=["crew-status"])

_allow_captain = RoleChecker(["driver", "trainer", "dispatch", "management", "admin"])


@router.get("/{target_date}", response_model=CrewStatusResponse)
def get_crew_status(
    target_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_captain),
    db: Session = Depends(get_db),
):
    cid = caller.company_id

    # Truck scope: oversight sees all trucks; field captains/drivers see their own.
    ta_query = db.query(TruckAssignment).filter(
        TruckAssignment.date == target_date,
        TruckAssignment.company_id == cid,
    )
    if caller.role not in OVERSIGHT_ROLES:
        own = (
            db.query(AssignmentMember)
            .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                AssignmentMember.employee_id == caller.id,
                AssignmentMember.company_id == cid,
                TruckAssignment.date == target_date,
                TruckAssignment.company_id == cid,
            )
            .first()
        )
        if own is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You are not assigned to a truck on this date.")
        ta_query = ta_query.filter(TruckAssignment.id == own.assignment_id)

    truck_assignments = ta_query.all()
    if not truck_assignments:
        return CrewStatusResponse(date=target_date, completion_threshold=DEFAULT_COMPLETION_THRESHOLD, trucks=[])

    # Names for every employee referenced across all trucks (one query).
    all_members = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id.in_([ta.id for ta in truck_assignments]),
        AssignmentMember.company_id == cid,
    ).all()
    emp_ids = {m.employee_id for m in all_members}
    names = {
        e.id: e.name for e in db.query(Employee).filter(
            Employee.id.in_(emp_ids), Employee.company_id == cid,
        ).all()
    } if emp_ids else {}

    # Roll-call presence for the date (ADR-198/199), one query for the whole set.
    # present tri-state: True = early/present/late; False = ncns (absent);
    # None = no record yet → 'not_arrived'. This is the gate that flips a member
    # from Not Arrived into the working crew status once roll call is taken.
    roll_calls = {
        rc.employee_id: rc.status
        for rc in db.query(ShiftRollCall).filter(
            ShiftRollCall.employee_id.in_(emp_ids),
            ShiftRollCall.date == target_date,
            ShiftRollCall.company_id == cid,
        ).all()
    } if emp_ids else {}

    def _present(employee_id):
        st = roll_calls.get(employee_id)
        if st is None:
            return None
        if st == "ncns":
            return False
        return True   # early | present | late

    trucks: list[CrewStatusTruck] = []
    for ta in truck_assignments:
        members = [m for m in all_members if m.assignment_id == ta.id]
        truck = db.query(Truck).filter(Truck.id == ta.truck_id, Truck.company_id == cid).first()

        # Availability inputs per member (mirrors the /availability endpoint).
        progress: list[MemberProgress] = []
        pct_by_emp: dict = {}
        for m in members:
            has_route = False
            pct = None
            if m.status == "active":
                route = db.query(Route).filter(
                    Route.company_id == cid,
                    Route.truck_assignment_id == ta.id,
                    Route.returned_at.is_(None),
                    Route.status.in_(("assigned", "in_progress")),
                    (Route.assigned_to == m.employee_id) | (Route.paired_trainee_id == m.employee_id),
                ).first()
                if route is not None:
                    has_route = True
                    total = db.query(DeliveryStop).filter(
                        DeliveryStop.route_id == route.id, DeliveryStop.company_id == cid,
                    ).count()
                    done = db.query(DeliveryStop).filter(
                        DeliveryStop.route_id == route.id, DeliveryStop.company_id == cid,
                        DeliveryStop.status == "completed",
                    ).count()
                    pct = (done / total) if total else 0.0
            pct_by_emp[m.employee_id] = pct
            progress.append(MemberProgress(
                employee_id=m.employee_id, name=names.get(m.employee_id), role=m.role,
                membership_status=m.status, has_active_route=has_route, route_completion_pct=pct,
                present=_present(m.employee_id),
            ))

        _entries, active_crew, available = derive_availability(progress)

        # Pairing maps for this truck. trainer_present = trainer is an ACTIVE member
        # who has arrived at the AP (ap_arrived_at set). A trainee whose trainer is
        # not present is orphaned → the Phase B reassignment entry point.
        member_by_emp = {m.employee_id: m for m in members}
        crew_members: list[CrewStatusMember] = []
        for m in members:
            av = classify_member(
                MemberProgress(
                    employee_id=m.employee_id, name=names.get(m.employee_id), role=m.role,
                    membership_status=m.status, has_active_route=(pct_by_emp.get(m.employee_id) is not None),
                    route_completion_pct=pct_by_emp.get(m.employee_id),
                    present=_present(m.employee_id),
                )
            )
            paired_trainer_id = m.paired_trainer_id if m.role == ROLE_TRAINEE else None
            paired_trainee = None
            if m.role != ROLE_TRAINEE:
                paired_trainee = next(
                    (t for t in members if t.role == ROLE_TRAINEE and t.paired_trainer_id == m.employee_id),
                    None,
                )

            orphaned = False
            if m.role == ROLE_TRAINEE and paired_trainer_id is not None:
                trainer_m = member_by_emp.get(paired_trainer_id)
                trainer_present = (
                    trainer_m is not None
                    and trainer_m.status == "active"
                    and trainer_m.ap_arrived_at is not None
                )
                # Only flag once the trainee themselves has arrived — a trainer who
                # simply hasn't tapped yet pre-shift is not an emergency.
                orphaned = (m.ap_arrived_at is not None) and not trainer_present

            crew_members.append(CrewStatusMember(
                member_id=m.id,
                employee_id=m.employee_id,
                name=names.get(m.employee_id),
                role=m.role,
                membership_status=m.status,
                availability=av.availability,
                route_completion_pct=av.route_completion_pct,
                trip_count=m.trip_count or 0,
                paired_trainer_id=paired_trainer_id,
                paired_trainer_name=names.get(paired_trainer_id) if paired_trainer_id else None,
                paired_trainee_id=paired_trainee.employee_id if paired_trainee else None,
                paired_trainee_name=names.get(paired_trainee.employee_id) if paired_trainee else None,
                orphaned=orphaned,
            ))

        trucks.append(CrewStatusTruck(
            truck_assignment_id=ta.id,
            truck_id=ta.truck_id,
            truck_name=truck.name if truck else None,
            active_crew=active_crew,
            available_for_route=available,
            members=crew_members,
        ))

    return CrewStatusResponse(
        date=target_date,
        completion_threshold=DEFAULT_COMPLETION_THRESHOLD,
        trucks=trucks,
    )
