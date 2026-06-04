from datetime import datetime, date, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.shift_session import ShiftSession
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember

router = APIRouter(prefix="/shift-sessions", tags=["shift-sessions"])

allow_driver = RoleChecker(["driver"])
allow_mgmt   = RoleChecker(["management", "admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ShiftSessionResponse(BaseModel):
    id: UUID
    driver_id: UUID
    current_gate: int
    started_at: datetime
    gate_1_completed_at: datetime | None
    gate_2_completed_at: datetime | None
    gate_3_completed_at: datetime | None
    gate_4_completed_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Start shift — creates a new session (Gate 1)
# ---------------------------------------------------------------------------

@router.post("/", response_model=ShiftSessionResponse, status_code=status.HTTP_201_CREATED)
def start_shift(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
    db: Session = Depends(get_db),
):
    """Start a new shift session for the calling driver. Fails if one is already active."""
    today = date.today()
    assigned = (
        db.query(TruckAssignment)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == today,
            AssignmentMember.employee_id == caller.id,
        )
        .first()
    )
    if not assigned:
        raise HTTPException(
            status_code=400,
            detail="You are not assigned to a truck for today. Contact your dispatcher.",
        )

    existing = db.query(ShiftSession).filter(
        ShiftSession.driver_id == caller.id,
        ShiftSession.company_id == caller.company_id,
        ShiftSession.completed_at.is_(None),
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="You already have an active shift session. Complete or abandon it before starting a new one.",
        )

    session = ShiftSession(
        company_id=caller.company_id,
        driver_id=caller.id,
        current_gate=1,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# ---------------------------------------------------------------------------
# Eligibility check — is the driver assigned to a truck today?
# ---------------------------------------------------------------------------

@router.get("/me/eligible", response_model=bool)
def check_eligibility(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
    db: Session = Depends(get_db),
):
    """Return true if the driver is assigned to a truck today."""
    today = date.today()
    assigned = (
        db.query(TruckAssignment)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == today,
            AssignmentMember.employee_id == caller.id,
        )
        .first()
    )
    return assigned is not None


# ---------------------------------------------------------------------------
# Get active session for the calling driver
# ---------------------------------------------------------------------------

@router.get("/me/active", response_model=ShiftSessionResponse | None)
def get_my_active_session(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
    db: Session = Depends(get_db),
):
    """Return the caller's current active shift session, or null if none exists."""
    return db.query(ShiftSession).filter(
        ShiftSession.driver_id == caller.id,
        ShiftSession.company_id == caller.company_id,
        ShiftSession.completed_at.is_(None),
    ).first()


# ---------------------------------------------------------------------------
# Advance gate — driver signals they've completed the current gate
# ---------------------------------------------------------------------------

@router.patch("/me/active/advance", response_model=ShiftSessionResponse)
def advance_gate(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
    db: Session = Depends(get_db),
):
    """Advance the active session to the next gate. Idempotent if already at gate 5."""
    session = db.query(ShiftSession).filter(
        ShiftSession.driver_id == caller.id,
        ShiftSession.company_id == caller.company_id,
        ShiftSession.completed_at.is_(None),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="No active shift session found.")

    now = datetime.now(timezone.utc)
    gate = session.current_gate

    if gate == 1:
        session.gate_1_completed_at = now
        session.current_gate = 2
    elif gate == 2:
        session.gate_2_completed_at = now
        session.current_gate = 3
    elif gate == 3:
        session.gate_3_completed_at = now
        session.current_gate = 4
    elif gate == 4:
        session.gate_4_completed_at = now
        session.current_gate = 5
    elif gate == 5:
        # Gate 5 completion = end of shift
        session.completed_at = now
    else:
        raise HTTPException(status_code=400, detail="Invalid gate state.")

    db.commit()
    db.refresh(session)
    return session


# ---------------------------------------------------------------------------
# Skip forward — emergency access to bypass a gate (driver-initiated)
# ---------------------------------------------------------------------------

@router.patch("/me/active/skip-to/{gate}", response_model=ShiftSessionResponse)
def skip_to_gate(
    gate: int,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
    db: Session = Depends(get_db),
):
    """Skip forward to a specific gate. Only allows skipping forward, never backward.
    Used when a driver is blocked (e.g. backend error) and needs to proceed.
    """
    if gate < 1 or gate > 5:
        raise HTTPException(status_code=400, detail="Gate must be between 1 and 5.")

    session = db.query(ShiftSession).filter(
        ShiftSession.driver_id == caller.id,
        ShiftSession.company_id == caller.company_id,
        ShiftSession.completed_at.is_(None),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="No active shift session found.")

    if gate <= session.current_gate:
        raise HTTPException(status_code=400, detail="Cannot skip backward to a previous gate.")

    now = datetime.now(timezone.utc)
    # Stamp completion timestamps for any skipped gates
    if session.current_gate <= 1 and gate > 1:
        session.gate_1_completed_at = session.gate_1_completed_at or now
    if session.current_gate <= 2 and gate > 2:
        session.gate_2_completed_at = session.gate_2_completed_at or now
    if session.current_gate <= 3 and gate > 3:
        session.gate_3_completed_at = session.gate_3_completed_at or now
    if session.current_gate <= 4 and gate > 4:
        session.gate_4_completed_at = session.gate_4_completed_at or now

    session.current_gate = gate
    db.commit()
    db.refresh(session)
    return session


# ---------------------------------------------------------------------------
# Abandon — management can force-close a stuck session
# ---------------------------------------------------------------------------

@router.delete("/driver/{driver_id}/active", status_code=status.HTTP_204_NO_CONTENT)
def abandon_session(
    driver_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    """Force-complete a driver's active session. Management/admin only."""
    session = db.query(ShiftSession).filter(
        ShiftSession.driver_id == driver_id,
        ShiftSession.company_id == caller.company_id,
        ShiftSession.completed_at.is_(None),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="No active session found for this driver.")

    session.completed_at = datetime.now(timezone.utc)
    db.commit()
