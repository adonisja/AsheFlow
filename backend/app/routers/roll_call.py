"""Roll call router — unified shift attendance for drivers and trainers.

POST  /roll-call                  — submit attendance for a crew member
PATCH /roll-call/{id}/confirm     — confirm an entry (second-tap requirement)
PATCH /roll-call/{id}             — dispatch/admin override
GET   /roll-call/my-truck/{date}  — own-truck view (driver, trainer)
GET   /roll-call/summary/{date}   — full-date view (dispatch, mgmt, admin)
"""
import os
import threading
import logging
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_caller_employee, RoleChecker
from app.models.employee import Employee
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.shift_roll_call import ShiftRollCall
from app.models.truck import Truck
from app.models.training import TrainingRecord
from app.models.notification import Notification
from app.models.company import CompanyConfig, Company
from app.schemas.roll_call import (
    RollCallCreate, RollCallOverride, RollCallResponse, RollCallSummaryEntry,
)
from app.services.audit import write_audit
from app.services.local_date import company_tz
from app.services.constants import ROLE_DRIVER, ROLE_TRAINER, ROLE_TRAINEE, OVERSIGHT_ROLES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roll-call", tags=["roll-call"])

_allow_field     = RoleChecker(["driver", "trainer", "dispatch", "management", "admin"])
_allow_dispatch  = RoleChecker(["dispatch", "management", "admin"])

DEFAULT_LATE_WINDOW = 20  # minutes — used when CompanyConfig.late_window_minutes is NULL
DEFAULT_NCNS_CUTOFF = 60  # minutes past reference — used when ncns_cutoff_minutes is NULL (ADR-198)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attendance_reference(
    shift_start,
    ap_established_local: Optional[datetime],
    tz: ZoneInfo,
    on_date,
) -> Optional[datetime]:
    """The attendance clock reference (ADR-198 D2): max(shift_start, AP-established).

    - shift_start is an ABSOLUTE FLOOR: an EARLY driver/AP is ignored (crew judged
      against the schedule, never earlier).
    - a LATE AP raises the reference to the actual AP-established time (so a
      station-delayed driver doesn't mark the on-time crew late/NCNS).
    - if the AP was never established, fall back to the floor (shift_start).
    Returns None only when there is no shift_start at all (→ caller treats as
    always-present, preserving prior no-config behavior).

    Pure/DB-free for testability; caller resolves shift_start, ap_established, tz.
    """
    if shift_start is None:
        return None
    floor_dt = datetime.combine(on_date, shift_start, tzinfo=tz)
    if ap_established_local is None:
        return floor_dt
    ap_dt = ap_established_local.astimezone(tz)
    return max(floor_dt, ap_dt)


def _ap_established_time(db: Session, employee_id, on_date, company_id) -> Optional[datetime]:
    """When the AP became available for this crew member's truck (ADR-198).

    = the driver's AnchorPoint reaching 'arrived' for the member's truck+date.
    The driver establishes the AP; everyone else's attendance clock is measured
    against it (floored at shift_start). Returns None if no arrived AP yet (→
    reference falls back to the shift_start floor).
    """
    from app.models.anchor_point import AnchorPoint

    am = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == employee_id,
            AssignmentMember.company_id == company_id,
            TruckAssignment.date == on_date,
            TruckAssignment.company_id == company_id,
        )
        .first()
    )
    if am is None:
        return None
    ta = db.query(TruckAssignment).filter(TruckAssignment.id == am.assignment_id).first()
    if ta is None:
        return None
    ap = (
        db.query(AnchorPoint)
        .filter(
            AnchorPoint.truck_id == ta.truck_id,
            AnchorPoint.date == on_date,
            AnchorPoint.company_id == company_id,
            AnchorPoint.status == "arrived",
            AnchorPoint.arrived_at.isnot(None),
        )
        .order_by(AnchorPoint.arrived_at.asc())
        .first()
    )
    return ap.arrived_at if ap else None


def _derive_status(
    reference: Optional[datetime],
    late_window_minutes: Optional[int],
    arrival_local: datetime,
    ncns_cutoff_minutes: Optional[int] = None,
) -> str:
    """'early'|'present'|'late'|'ncns' from arrival time vs the attendance reference.

    reference = max(shift_start, AP-established) from _attendance_reference. None
    (no shift_start configured) → 'present'. Arrival past reference + NCNS cutoff
    with the flow marking absence → 'ncns' (the caller passes arrival=reference+∞
    semantics via the cutoff; here a positive ncns test is delegated to the
    caller which knows whether an AP arrival actually happened).
    """
    if reference is None:
        return "present"
    delta_minutes = (arrival_local - reference).total_seconds() / 60
    window = late_window_minutes if late_window_minutes is not None else DEFAULT_LATE_WINDOW
    ncns_cut = ncns_cutoff_minutes if ncns_cutoff_minutes is not None else DEFAULT_NCNS_CUTOFF
    if delta_minutes < 0:
        return "early"
    if delta_minutes <= window:
        return "present"
    if delta_minutes > ncns_cut:
        return "ncns"
    return "late"


def _get_company_cfg(db: Session, company_id):
    return db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()


def derive_roll_call_status(db: Session, employee_id, target_date, company_id) -> str:
    """Derive 'early'|'present'|'late'|'ncns' for an on-time arrival right now.

    ADR-198: measure against max(shift_start, AP-established) — a late driver
    doesn't penalize on-time crew, and an early driver can't make them look late
    (the shift_start floor). Shared by submit_roll_call and the trainee arrival
    tap (ADR-199 D1) so both derive attendance identically.
    """
    cfg = _get_company_cfg(db, company_id)
    tz = company_tz(db, company_id)
    ap_established = _ap_established_time(db, employee_id, target_date, company_id)
    reference = _attendance_reference(
        shift_start=cfg.shift_start if cfg else None,
        ap_established_local=ap_established,
        tz=tz,
        on_date=datetime.now(tz).date(),
    )
    return _derive_status(
        reference=reference,
        late_window_minutes=cfg.late_window_minutes if cfg else None,
        arrival_local=datetime.now(timezone.utc).astimezone(tz),
        ncns_cutoff_minutes=cfg.ncns_cutoff_minutes if cfg else None,
    )


def upsert_arrival_roll_call(db: Session, employee_id, target_date, company_id, submitted_by_id):
    """Record attendance for a crew member's own AP arrival (ADR-199 D1).

    The trainee's "I've arrived" tap IS their roll-call: roll-call happens at the
    AP (ADR-198), so the arrival event and the roll-call are the same real event.
    Idempotent — if a record already exists for (employee_id, date) it is left as
    is (the arrival tap never downgrades a status a driver/dispatch already set).
    Derives status via the shared ADR-198 attendance logic. Does NOT commit —
    the caller flushes/audits/commits in its own transaction. Returns the row
    (existing or newly added), or None if one already existed.
    """
    existing = db.query(ShiftRollCall).filter(
        ShiftRollCall.employee_id == employee_id,
        ShiftRollCall.date == target_date,
        ShiftRollCall.company_id == company_id,
    ).first()
    if existing is not None:
        return None

    derived_status = derive_roll_call_status(db, employee_id, target_date, company_id)
    row = ShiftRollCall(
        company_id      = company_id,
        submitted_by_id = submitted_by_id,
        employee_id     = employee_id,
        date            = target_date,
        status          = derived_status,
    )
    db.add(row)
    return row


def _get_caller_truck_assignment(db: Session, caller: Employee, target_date: date) -> Optional[TruckAssignment]:
    """Return the TruckAssignment for the caller's truck on the given date, or None."""
    am = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == caller.id,
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if am is None:
        return None
    return db.query(TruckAssignment).filter(TruckAssignment.id == am.assignment_id).first()


def _fire_revoke_member(discord_id: str, channel_id: str, company_id: str) -> None:
    """Fire-and-forget: ask bot to revoke a member's truck channel access."""
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")

    def _run():
        try:
            http_requests.post(
                f"{bot_url}/internal/revoke-member",
                json={"discord_id": discord_id, "channel_id": channel_id, "company_id": company_id},
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("revoke-member webhook failed discord_id=%s: %s", discord_id, exc)

    threading.Thread(target=_run, daemon=True).start()


def _apply_ncns_side_effects(db: Session, trainee: Employee, target_date: date, company_id, caller_company_id) -> None:
    """Lock training record, void pairing, revert 1.5× capacity, notify dispatch.

    Called when status='ncns' is written for a trainee — same effects as
    trainee self-decline. Does NOT commit — caller must commit after write_audit.
    """
    # 1. Lock today's TrainingRecord so no tasks can be written or submitted.
    record = (
        db.query(TrainingRecord)
        .filter(
            TrainingRecord.trainee_id == trainee.id,
            TrainingRecord.record_date == target_date,
            TrainingRecord.company_id == company_id,
        )
        .first()
    )
    if record:
        record.is_locked = True

    # 2. Null out paired_trainer_id on the trainee's AssignmentMember.
    trainee_am = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == trainee.id,
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == company_id,
        )
        .first()
    )
    if trainee_am:
        trainee_am.paired_trainer_id = None

    # 3. Revert 1.5× capacity if arrival-confirm has already fired (ADR-198 D4).
    # NB: this clears the paired CEILING only — ADR-145's structural tote
    # absorption is not reversed (matches prior intent). Previously imported a
    # non-existent `WalkerRoute` model → ImportError/500 whenever this fired; now
    # uses the real `Route` model (assigned_to / route_date).
    if trainee_am:
        ta = db.query(TruckAssignment).filter(TruckAssignment.id == trainee_am.assignment_id).first()
        if ta and ta.paired_arrival_confirmed:
            ta.paired_arrival_confirmed = False
            from app.models.walker_route import Route
            trainer_am = (
                db.query(AssignmentMember)
                .filter(
                    AssignmentMember.assignment_id == ta.id,
                    AssignmentMember.role == ROLE_TRAINER,
                )
                .first()
            )
            if trainer_am:
                route = (
                    db.query(Route)
                    .filter(
                        Route.assigned_to == trainer_am.employee_id,
                        Route.route_date == target_date,
                        Route.company_id == company_id,
                    )
                    .first()
                )
                if route:
                    route.capacity_limit_paired = None

    # 4. Notify all dispatch/management/admin employees.
    oversight = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(list(OVERSIGHT_ROLES)),
            Employee.is_active == True,
        )
        .all()
    )
    for staff in oversight:
        db.add(Notification(
            employee_id=staff.id,
            company_id=company_id,
            type="trainee_ncns",
            message=(
                f"⚠️ **Trainee NCNS:** {trainee.name} did not show up for {target_date}. "
                f"Training record locked. Trainer freed from pairing duty."
            ),
            dispatch_date=target_date,
        ))


# ---------------------------------------------------------------------------
# POST /roll-call — submit attendance
# ---------------------------------------------------------------------------

@router.post("", response_model=RollCallResponse, status_code=status.HTTP_201_CREATED)
def submit_roll_call(
    payload: RollCallCreate,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_field),
):
    """Submit or upsert an attendance record for a crew member.

    Status is derived from wall-clock time vs CompanyConfig.shift_start.
    Pass ncns=True to explicitly mark a no-call no-show; this bypasses the
    time-based derivation and triggers side-effects if the target is a trainee.

    Authorization:
    - Driver: can mark any crew member on their truck.
    - Trainer: can only mark their paired trainee.
    - Dispatch/mgmt/admin: can mark anyone.
    """
    target_employee_id = payload.employee_id
    target_date = payload.date

    # Fetch target employee — must be in same company.
    target = db.query(Employee).filter(
        Employee.id == target_employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found.")

    # Authorization checks for field staff.
    if caller.role not in OVERSIGHT_ROLES:
        caller_ta = _get_caller_truck_assignment(db, caller, target_date)
        if caller_ta is None:
            raise HTTPException(status_code=403, detail="You are not assigned to a truck today.")

        if caller.role == ROLE_TRAINER:
            # Trainer may only mark their paired trainee.
            paired_am = (
                db.query(AssignmentMember)
                .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
                .filter(
                    AssignmentMember.paired_trainer_id == caller.id,
                    AssignmentMember.role == ROLE_TRAINEE,
                    TruckAssignment.date == target_date,
                    TruckAssignment.company_id == caller.company_id,
                )
                .first()
            )
            if paired_am is None or paired_am.employee_id != target_employee_id:
                raise HTTPException(
                    status_code=403,
                    detail="Trainers can only submit roll call for their paired trainee.",
                )
        else:
            # Driver: target must be on the same truck.
            target_am = (
                db.query(AssignmentMember)
                .filter(
                    AssignmentMember.assignment_id == caller_ta.id,
                    AssignmentMember.employee_id == target_employee_id,
                )
                .first()
            )
            if target_am is None:
                raise HTTPException(
                    status_code=403,
                    detail="You can only submit roll call for crew members on your truck.",
                )

    # Derive status from time (or explicit NCNS).
    if payload.ncns:
        derived_status = "ncns"
    else:
        cfg = _get_company_cfg(db, caller.company_id)
        tz  = company_tz(db, caller.company_id)
        # ADR-198: measure against max(shift_start, AP-established), not shift_start
        # alone — so a late driver doesn't penalize on-time crew, and an early
        # driver can't make normal-time crew look late (floor).
        ap_established = _ap_established_time(db, target_employee_id, target_date, caller.company_id)
        reference = _attendance_reference(
            shift_start=cfg.shift_start if cfg else None,
            ap_established_local=ap_established,
            tz=tz,
            on_date=datetime.now(tz).date(),
        )
        derived_status = _derive_status(
            reference=reference,
            late_window_minutes=cfg.late_window_minutes if cfg else None,
            arrival_local=datetime.now(timezone.utc).astimezone(tz),
            ncns_cutoff_minutes=cfg.ncns_cutoff_minutes if cfg else None,
        )

    # Upsert — one canonical record per (employee_id, date).
    now = datetime.now(timezone.utc)
    existing = db.query(ShiftRollCall).filter(
        ShiftRollCall.employee_id == target_employee_id,
        ShiftRollCall.date == target_date,
        ShiftRollCall.company_id == caller.company_id,
    ).first()

    if existing:
        if caller.role not in OVERSIGHT_ROLES:
            raise HTTPException(
                status_code=409,
                detail="A roll call record already exists for this employee today. Contact dispatch to update it.",
            )
        # Dispatch/admin override.
        existing.status       = derived_status
        existing.notes        = payload.notes
        existing.updated_by_id = caller.id
        existing.updated_at   = now
        existing.confirmed    = False
        existing.confirmed_at = None
        row = existing
    else:
        row = ShiftRollCall(
            company_id      = caller.company_id,
            submitted_by_id = caller.id,
            employee_id     = target_employee_id,
            date            = target_date,
            status          = derived_status,
            notes           = payload.notes,
        )
        db.add(row)

    db.flush()

    # NCNS side-effects for trainees.
    if derived_status == "ncns" and target.role == ROLE_TRAINEE:
        _apply_ncns_side_effects(db, target, target_date, caller.company_id, caller.company_id)

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="roll_call.submit",
        target_table="shift_roll_calls",
        target_id=str(row.id),
        detail={"employee_id": str(target_employee_id), "date": str(target_date), "status": derived_status},
    )
    db.commit()
    db.refresh(row)

    # Fire Discord revocation after commit if trainee NCNS.
    if derived_status == "ncns" and target.role == ROLE_TRAINEE and target.discord_id:
        # Find the truck channel_id for this trainee's assignment.
        ta = _get_caller_truck_assignment(db, target, target_date)
        if ta is None:
            # Look it up directly since target is not caller.
            am = (
                db.query(AssignmentMember)
                .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
                .filter(
                    AssignmentMember.employee_id == target_employee_id,
                    TruckAssignment.date == target_date,
                    TruckAssignment.company_id == caller.company_id,
                )
                .first()
            )
            if am:
                ta = db.query(TruckAssignment).filter(TruckAssignment.id == am.assignment_id).first()

        if ta:
            truck = db.query(Truck).filter(Truck.id == ta.truck_id).first()
            if truck and truck.discord_channel_id:
                _fire_revoke_member(
                    discord_id=str(target.discord_id),
                    channel_id=str(truck.discord_channel_id),
                    company_id=str(caller.company_id),
                )

    return RollCallResponse.model_validate(row, from_attributes=True)


# ---------------------------------------------------------------------------
# PATCH /roll-call/{id}/confirm — second-tap confirmation
# ---------------------------------------------------------------------------

@router.patch("/{roll_call_id}/confirm", response_model=RollCallResponse)
def confirm_roll_call(
    roll_call_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_field),
):
    """Confirm an existing roll call entry.

    Driver and trainer can confirm entries on their own truck.
    Dispatch/mgmt/admin can confirm any entry.
    """
    row = db.query(ShiftRollCall).filter(
        ShiftRollCall.id == roll_call_id,
        ShiftRollCall.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Roll call record not found.")

    if row.confirmed:
        raise HTTPException(status_code=409, detail="Roll call entry is already confirmed.")

    # Field staff can only confirm entries on their own truck.
    if caller.role not in OVERSIGHT_ROLES:
        caller_ta = _get_caller_truck_assignment(db, caller, row.date)
        if caller_ta is None:
            raise HTTPException(status_code=403, detail="You are not assigned to a truck on that date.")
        member_on_truck = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == caller_ta.id,
            AssignmentMember.employee_id == row.employee_id,
        ).first()
        if not member_on_truck:
            raise HTTPException(status_code=403, detail="You can only confirm roll call entries for your truck.")

    now = datetime.now(timezone.utc)
    row.confirmed    = True
    row.confirmed_at = now
    row.updated_at   = now
    row.updated_by_id = caller.id

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="roll_call.confirm",
        target_table="shift_roll_calls",
        target_id=str(row.id),
        detail={"employee_id": str(row.employee_id), "date": str(row.date)},
    )
    db.commit()
    db.refresh(row)
    return RollCallResponse.model_validate(row, from_attributes=True)


# ---------------------------------------------------------------------------
# PATCH /roll-call/{id} — dispatch/admin override
# ---------------------------------------------------------------------------

@router.patch("/{roll_call_id}", response_model=RollCallResponse)
def override_roll_call(
    roll_call_id: UUID,
    payload: RollCallOverride,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_dispatch),
):
    """Override status or notes on an existing roll call entry.

    Dispatch, management, and admin only. Resets confirmed to False so the
    updated record must be re-confirmed.
    """
    row = db.query(ShiftRollCall).filter(
        ShiftRollCall.id == roll_call_id,
        ShiftRollCall.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Roll call record not found.")

    prev_status   = row.status
    now           = datetime.now(timezone.utc)
    row.status    = payload.status
    row.notes     = payload.notes if payload.notes is not None else row.notes
    row.updated_by_id = caller.id
    row.updated_at    = now
    row.confirmed     = False
    row.confirmed_at  = None

    # If overriding TO ncns for a trainee, apply side-effects.
    if payload.status == "ncns" and prev_status != "ncns":
        target = db.query(Employee).filter(
            Employee.id == row.employee_id,
            Employee.company_id == caller.company_id,
        ).first()
        if target and target.role == ROLE_TRAINEE:
            _apply_ncns_side_effects(db, target, row.date, caller.company_id, caller.company_id)

    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="roll_call.override",
        target_table="shift_roll_calls",
        target_id=str(row.id),
        detail={"prev_status": prev_status, "new_status": payload.status, "date": str(row.date)},
    )
    db.commit()
    db.refresh(row)
    return RollCallResponse.model_validate(row, from_attributes=True)


# ---------------------------------------------------------------------------
# GET /roll-call/my-truck/{date} — driver/trainer view
# ---------------------------------------------------------------------------

@router.get("/my-truck/{target_date}", response_model=List[RollCallSummaryEntry])
def get_my_truck_roll_call(
    target_date: date,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_field),
):
    """Return roll call entries for all crew members on the caller's truck.

    Dispatch/mgmt/admin are redirected to /summary/{date} for full access.
    """
    if caller.role in OVERSIGHT_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Use GET /roll-call/summary/{date} for full-date access.",
        )

    caller_ta = _get_caller_truck_assignment(db, caller, target_date)
    if caller_ta is None:
        raise HTTPException(status_code=404, detail="You are not assigned to a truck on that date.")

    members = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == caller_ta.id,
    ).all()
    member_ids = [m.employee_id for m in members]

    return _build_summary_entries(db, member_ids, target_date, caller_ta, caller.company_id)


# ---------------------------------------------------------------------------
# GET /roll-call/summary/{date} — dispatch full view
# ---------------------------------------------------------------------------

@router.get("/summary/{target_date}", response_model=List[RollCallSummaryEntry])
def get_roll_call_summary(
    target_date: date,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_dispatch),
):
    """Return all roll call entries for a date across all trucks."""
    # Get all TruckAssignments for this date and company.
    tas = db.query(TruckAssignment).filter(
        TruckAssignment.date == target_date,
        TruckAssignment.company_id == caller.company_id,
    ).all()

    all_entries: List[RollCallSummaryEntry] = []
    for ta in tas:
        members = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == ta.id,
        ).all()
        member_ids = [m.employee_id for m in members]
        all_entries.extend(_build_summary_entries(db, member_ids, target_date, ta, caller.company_id))
    return all_entries


# ---------------------------------------------------------------------------
# Shared builder
# ---------------------------------------------------------------------------

def _build_summary_entries(
    db: Session,
    member_ids: list,
    target_date: date,
    ta: TruckAssignment,
    company_id,
) -> List[RollCallSummaryEntry]:
    truck = db.query(Truck).filter(Truck.id == ta.truck_id).first()
    truck_name = truck.name if truck else None

    roll_calls = {
        str(r.employee_id): r
        for r in db.query(ShiftRollCall).filter(
            ShiftRollCall.employee_id.in_(member_ids),
            ShiftRollCall.date == target_date,
            ShiftRollCall.company_id == company_id,
        ).all()
    }

    employees = {
        str(e.id): e
        for e in db.query(Employee).filter(Employee.id.in_(member_ids)).all()
    }

    entries = []
    for emp_id in member_ids:
        emp = employees.get(str(emp_id))
        if not emp:
            continue
        rc = roll_calls.get(str(emp_id))
        submitter_name = None
        if rc and rc.submitted_by_id:
            sub = employees.get(str(rc.submitted_by_id))
            if sub is None:
                sub = db.query(Employee).filter(Employee.id == rc.submitted_by_id).first()
            submitter_name = sub.name if sub else None

        entries.append(RollCallSummaryEntry(
            id               = rc.id if rc else None,
            employee_id      = emp.id,
            employee_name    = emp.name,
            role             = emp.role,
            truck_name       = truck_name,
            status           = rc.status if rc else "pending",
            confirmed        = rc.confirmed if rc else False,
            submitted_by_name= submitter_name,
            submitted_at     = rc.submitted_at if rc else None,
            notes            = rc.notes if rc else None,
        ))
    return entries
