from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, assert_owns_or_privileged
from app.core.config import settings
from app.models.field_ops import CheckIn, Departure, WalkerRating, VehicleInspection, FuelMileageLog, INSPECTION_ITEMS
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.notification import Notification
from app.schemas.field_ops import (
    CheckInCreate, CheckInResponse,
    DepartureCreate, DepartureResponse,
    WalkerRatingCreate, WalkerRatingResponse,
    VehicleInspectionCreate, VehicleInspectionResponse, VehicleInspectionSummaryItem,
    FuelMileageLogCreate, FuelMileageLogPatch, FuelMileageLogResponse, FuelMileageSummaryItem,
)

router = APIRouter(prefix="/field-ops", tags=["field-ops"])

allow_field_staff = RoleChecker(["driver", "walker", "trainer", "trainee"])
allow_driver      = RoleChecker(["driver"])
allow_management  = RoleChecker(["dispatch", "management", "admin"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_truck_for_employee(employee_id: UUID, target_date: date, db: Session):
    """Return (truck_id, assignment_id) for employee on target_date, or (None, None)."""
    member_row = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == employee_id,
            TruckAssignment.date == target_date,
        )
        .first()
    )
    if not member_row:
        return None, None
    ta = db.query(TruckAssignment).filter(TruckAssignment.id == member_row.assignment_id).first()
    return (ta.truck_id if ta else None), member_row.assignment_id


# ---------------------------------------------------------------------------
# Crew helpers — who is on the same truck as this employee today?
# ---------------------------------------------------------------------------

@router.get("/crew/{employee_id}")
def get_today_crew(
    employee_id: UUID,
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return crew members on the same truck as employee_id for target_date (today if omitted).

    Callers may only request their own crew. Dispatch/management/admin may request any employee's crew.
    """
    assert_owns_or_privileged(caller, employee_id, "crew assignment")

    if target_date is None:
        target_date = date.today()

    # Find the assignment this employee belongs to
    member_row = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == employee_id,
            TruckAssignment.date == target_date,
        )
        .first()
    )

    if not member_row:
        return {"crew": []}

    # Get all members of that same assignment
    crew_rows = (
        db.query(AssignmentMember, Employee)
        .join(Employee, AssignmentMember.employee_id == Employee.id)
        .filter(
            AssignmentMember.assignment_id == member_row.assignment_id,
            AssignmentMember.employee_id != employee_id,   # exclude self
        )
        .all()
    )

    crew = [
        {"id": str(emp.id), "name": emp.name, "role": am.role}
        for am, emp in crew_rows
    ]
    return {"crew": crew}


# ---------------------------------------------------------------------------
# Check-In
# ---------------------------------------------------------------------------

@router.post("/check-in", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
def check_in(
    payload: CheckInCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    if payload.employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only check in yourself.")

    if payload.date != date.today():
        raise HTTPException(status_code=400, detail="Check-in date must be today.")

    existing = db.query(CheckIn).filter(
        CheckIn.employee_id == payload.employee_id,
        CheckIn.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already checked in for this date.")

    row = CheckIn(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/check-in/{employee_id}", response_model=List[CheckInResponse])
def get_check_ins(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    assert_owns_or_privileged(caller, employee_id)
    return db.query(CheckIn).filter(CheckIn.employee_id == employee_id).order_by(CheckIn.date.desc()).all()


@router.get("/check-ins/summary")
def get_check_ins_summary(
    target_date: date = None,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Return all check-ins for a given date with driver names. Management/admin use."""
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(CheckIn)
        .filter(CheckIn.date == target_date)
        .order_by(CheckIn.checked_in_at.asc())
        .all()
    )

    emp_ids = {r.employee_id for r in rows}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    return [
        {
            "employee_id": str(row.employee_id),
            "driver_name": emp_map[row.employee_id].name if row.employee_id in emp_map else "Unknown",
            "checked_in_at": row.checked_in_at.isoformat(),
            "date": row.date.isoformat(),
        }
        for row in rows
        if row.employee_id in emp_map and emp_map[row.employee_id].role == "driver"
    ]


# ---------------------------------------------------------------------------
# Departure
# ---------------------------------------------------------------------------

@router.post("/departure", response_model=DepartureResponse, status_code=status.HTTP_201_CREATED)
def record_departure(
    payload: DepartureCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    # Fix #2: caller can only record their own departure
    if payload.employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only record your own departure.")

    # Require check-in before departure can be recorded
    checked_in = db.query(CheckIn).filter(
        CheckIn.employee_id == payload.employee_id,
        CheckIn.date == payload.date,
    ).first()
    if not checked_in:
        raise HTTPException(status_code=400, detail="You must check in before recording a departure.")

    existing = db.query(Departure).filter(
        Departure.employee_id == payload.employee_id,
        Departure.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Departure already recorded for this date.")

    row = Departure(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/departure/{employee_id}", response_model=List[DepartureResponse])
def get_departures(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    assert_owns_or_privileged(caller, employee_id)
    return db.query(Departure).filter(Departure.employee_id == employee_id).order_by(Departure.date.desc()).all()


# ---------------------------------------------------------------------------
# Return / End-of-Day
# ---------------------------------------------------------------------------

@router.get("/returns/summary")
def get_returns_summary(
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_management),
):
    """Return a summary of all driver departures/returns for a given date.

    Intended for admin/management to monitor daily fleet activity.
    Includes shift duration where both departed_at and returned_at are present.
    """
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(Departure)
        .filter(Departure.date == target_date)
        .order_by(Departure.departed_at.asc())
        .all()
    )

    emp_ids = {r.employee_id for r in rows}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    result = []
    for row in rows:
        emp = emp_map.get(row.employee_id)
        if not emp or emp.role != "driver":
            continue
        duration_minutes = None
        if row.departed_at and row.returned_at:
            delta = row.returned_at - row.departed_at
            duration_minutes = int(delta.total_seconds() // 60)
        result.append({
            "employee_id": str(row.employee_id),
            "driver_name": emp.name,
            "departed_at": row.departed_at.isoformat() if row.departed_at else None,
            "returned_at": row.returned_at.isoformat() if row.returned_at else None,
            "duration_minutes": duration_minutes,
            "status": "returned" if row.returned_at else "out",
        })
    return result


@router.post("/return/{employee_id}", response_model=DepartureResponse)
def record_return(
    employee_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Stamp the return time on today's departure record.

    Requires a departure record for the same employee + date to exist.
    Idempotent if already returned — returns the existing record without error.
    """
    # Fix #2: caller can only record their own return
    if employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only record your own return.")

    today = date.today()
    departure = db.query(Departure).filter(
        Departure.employee_id == employee_id,
        Departure.date == today,
    ).first()

    if not departure:
        raise HTTPException(status_code=400, detail="No departure record found for today. You must depart before recording a return.")

    if departure.returned_at:
        return departure  # Already returned — idempotent

    departure.returned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(departure)
    return departure


# ---------------------------------------------------------------------------
# Walker Ratings
# ---------------------------------------------------------------------------

@router.post("/rating", response_model=WalkerRatingResponse, status_code=status.HTTP_201_CREATED)
def submit_rating(
    payload: WalkerRatingCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    # Fix #2: caller must be the driver
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit ratings as yourself.")

    # Gate 1 — departure must exist and driver must have departed
    departure = db.query(Departure).filter(
        Departure.employee_id == payload.driver_id,
        Departure.date == payload.date,
    ).first()
    if not departure or departure.departed_at is None:
        raise HTTPException(
            status_code=400,
            detail="Ratings can only be submitted after the driver has departed for the day.",
        )

    # Gate 2 — rating window must still be open
    now = datetime.now(timezone.utc)
    window_close = departure.departed_at + timedelta(hours=settings.rating_window_hours)
    if now > window_close:
        raise HTTPException(
            status_code=400,
            detail=f"The rating window has closed. Ratings must be submitted within {settings.rating_window_hours} hours of departure.",
        )

    if payload.present and (payload.stars is None or not (1 <= payload.stars <= 5)):
        raise HTTPException(status_code=400, detail="Stars must be between 1 and 5 for present walkers.")
    if not payload.present and payload.stars is not None:
        raise HTTPException(status_code=400, detail="Stars should not be provided for a no-show.")

    # Ensure the target walker actually exists before creating a rating record
    walker = db.query(Employee).filter(Employee.id == payload.walker_id).first()
    if not walker:
        raise HTTPException(status_code=404, detail="Walker not found.")

    # Fix #6: walker must be on the same truck as the driver today
    _, driver_assignment_id = _resolve_truck_for_employee(payload.driver_id, payload.date, db)
    if driver_assignment_id:
        walker_on_crew = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == driver_assignment_id,
            AssignmentMember.employee_id == payload.walker_id,
        ).first()
        if not walker_on_crew:
            raise HTTPException(
                status_code=400,
                detail="The specified walker is not assigned to your truck for this date.",
            )

    existing = db.query(WalkerRating).filter(
        WalkerRating.driver_id == payload.driver_id,
        WalkerRating.walker_id == payload.walker_id,
        WalkerRating.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already submitted attendance for this walker today.")

    row = WalkerRating(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/rating/walker/{walker_id}", response_model=List[WalkerRatingResponse])
def get_ratings_for_walker(
    walker_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_management),
):
    walker = db.query(Employee).filter(Employee.id == walker_id).first()
    if not walker:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return db.query(WalkerRating).filter(WalkerRating.walker_id == walker_id).order_by(WalkerRating.date.desc()).all()


@router.get("/rating/driver/{driver_id}", response_model=List[WalkerRatingResponse])
def get_ratings_by_driver(
    driver_id: UUID,
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all ratings submitted by a driver, optionally filtered to a single date.

    Used by WalkerRatingPanel on mount to pre-populate already-submitted ratings
    so a page refresh doesn't show walkers as unrated when they've already been rated.
    """
    assert_owns_or_privileged(caller, driver_id)
    driver = db.query(Employee).filter(Employee.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Employee not found.")
    q = db.query(WalkerRating).filter(WalkerRating.driver_id == driver_id)
    if target_date:
        q = q.filter(WalkerRating.date == target_date)
    return q.order_by(WalkerRating.date.desc()).all()


# ---------------------------------------------------------------------------
# Vehicle Inspection
# ---------------------------------------------------------------------------

@router.get("/inspection/items")
def get_inspection_items(caller: Employee = Depends(get_caller_employee)):
    """Return the canonical list of checklist items the client should render."""
    return {"items": INSPECTION_ITEMS}


@router.post("/inspection", response_model=VehicleInspectionResponse, status_code=status.HTTP_201_CREATED)
def submit_inspection(
    payload: VehicleInspectionCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit a pre-trip inspection. One allowed per driver per date."""
    # Fix #2: caller can only submit their own inspection
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit your own inspection.")

    existing = db.query(VehicleInspection).filter(
        VehicleInspection.driver_id == payload.driver_id,
        VehicleInspection.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Inspection already submitted for today.")

    # Fix #7: all canonical items must be present
    missing = [k for k in INSPECTION_ITEMS if k not in payload.items]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required inspection items: {missing}")

    unknown = [k for k in payload.items if k not in INSPECTION_ITEMS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown inspection items: {unknown}")

    # Auto-resolve truck from today's assignment
    truck_id, _ = _resolve_truck_for_employee(payload.driver_id, payload.date, db)

    has_failures = any(v is False for v in payload.items.values())

    row = VehicleInspection(
        driver_id=payload.driver_id,
        truck_id=truck_id,
        date=payload.date,
        items=payload.items,
        has_failures=has_failures,
        notes=payload.notes,
    )
    db.add(row)
    db.flush()  # get row.id before notifications

    if has_failures:
        failed_items = [k.replace("_", " ").title() for k, v in payload.items.items() if v is False]
        truck = db.query(Truck).filter(Truck.id == truck_id).first() if truck_id else None
        truck_label = truck.name if truck else "unassigned truck"
        message = (
            f"Pre-trip inspection FAILED — {caller.name} · {truck_label} · {payload.date}. "
            f"Failed items: {', '.join(failed_items)}."
        )
        recipients = db.query(Employee).filter(
            Employee.role.in_(["dispatch", "management", "admin"]),
            Employee.is_active == True,
        ).all()
        for recipient in recipients:
            db.add(Notification(
                employee_id=recipient.id,
                type="inspection_failed",
                message=message,
            ))

    db.commit()
    db.refresh(row)
    return row


@router.get("/inspection/{driver_id}", response_model=List[VehicleInspectionResponse])
def get_inspections(
    driver_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return inspection history for a driver (most recent first)."""
    assert_owns_or_privileged(caller, driver_id)
    return (
        db.query(VehicleInspection)
        .filter(VehicleInspection.driver_id == driver_id)
        .order_by(VehicleInspection.date.desc())
        .all()
    )


@router.get("/inspections/summary", response_model=List[VehicleInspectionSummaryItem])
def get_inspections_summary(
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_management),
):
    """Return all inspections for a given date with driver/truck names. Management use."""
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(VehicleInspection)
        .filter(VehicleInspection.date == target_date)
        .order_by(VehicleInspection.submitted_at.asc())
        .all()
    )

    emp_ids   = {r.driver_id for r in rows}
    truck_ids = {r.truck_id for r in rows if r.truck_id}
    emp_map   = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    result = []
    for row in rows:
        emp   = emp_map.get(row.driver_id)
        truck = truck_map.get(row.truck_id) if row.truck_id else None
        failed = [k for k, v in row.items.items() if v is False]
        result.append(VehicleInspectionSummaryItem(
            inspection_id=row.id,
            driver_name=emp.name if emp else "Unknown",
            truck_name=truck.name if truck else None,
            date=row.date,
            has_failures=row.has_failures,
            submitted_at=row.submitted_at,
            failed_items=failed,
        ))
    return result


# ---------------------------------------------------------------------------
# Fuel / Mileage Log
# ---------------------------------------------------------------------------

@router.post("/fuel-log", response_model=FuelMileageLogResponse, status_code=status.HTTP_201_CREATED)
def create_fuel_log(
    payload: FuelMileageLogCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit start-of-shift odometer reading. One record per driver per date."""
    # Fix #2: caller can only log for themselves
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit your own fuel log.")

    existing = db.query(FuelMileageLog).filter(
        FuelMileageLog.driver_id == payload.driver_id,
        FuelMileageLog.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Fuel log already started for today.")

    # Auto-resolve truck from today's assignment
    truck_id, _ = _resolve_truck_for_employee(payload.driver_id, payload.date, db)

    row = FuelMileageLog(
        driver_id=payload.driver_id,
        truck_id=truck_id,
        date=payload.date,
        odometer_start=payload.odometer_start,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/fuel-log/{driver_id}", response_model=FuelMileageLogResponse)
def update_fuel_log(
    driver_id: UUID,
    payload: FuelMileageLogPatch,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Patch today's fuel log with end-of-day odometer and fuel added."""
    # Fix #2: caller can only patch their own log
    if driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only update your own fuel log.")

    today = date.today()
    row = db.query(FuelMileageLog).filter(
        FuelMileageLog.driver_id == driver_id,
        FuelMileageLog.date == today,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No fuel log found for today. Submit start odometer first.")

    # Fix #5: once odometer_end is set it cannot be changed — prevents overwrite on retry
    if payload.odometer_end is not None:
        if row.odometer_end is not None and row.odometer_end != payload.odometer_end:
            raise HTTPException(
                status_code=400,
                detail="End odometer is already recorded and cannot be changed.",
            )
        if payload.odometer_end < row.odometer_start:
            raise HTTPException(status_code=400, detail="End odometer cannot be less than start odometer.")
        row.odometer_end = payload.odometer_end

    if payload.fuel_added is not None:
        row.fuel_added = payload.fuel_added
    if payload.notes is not None:
        row.notes = payload.notes

    db.commit()
    db.refresh(row)
    return row


@router.get("/fuel-log/{driver_id}", response_model=List[FuelMileageLogResponse])
def get_fuel_logs(
    driver_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return fuel log history for a driver (most recent first)."""
    assert_owns_or_privileged(caller, driver_id)
    return (
        db.query(FuelMileageLog)
        .filter(FuelMileageLog.driver_id == driver_id)
        .order_by(FuelMileageLog.date.desc())
        .all()
    )


@router.get("/fuel-logs/summary", response_model=List[FuelMileageSummaryItem])
def get_fuel_logs_summary(
    target_date: date = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_management),
):
    """Return all fuel logs for a given date. Management use."""
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(FuelMileageLog)
        .filter(FuelMileageLog.date == target_date)
        .order_by(FuelMileageLog.created_at.asc())
        .all()
    )

    emp_ids   = {r.driver_id for r in rows}
    truck_ids = {r.truck_id for r in rows if r.truck_id}
    emp_map   = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    result = []
    for row in rows:
        emp   = emp_map.get(row.driver_id)
        truck = truck_map.get(row.truck_id) if row.truck_id else None
        distance = (row.odometer_end - row.odometer_start) if row.odometer_end is not None else None
        result.append(FuelMileageSummaryItem(
            log_id=row.id,
            driver_name=emp.name if emp else "Unknown",
            truck_name=truck.name if truck else None,
            date=row.date,
            odometer_start=row.odometer_start,
            odometer_end=row.odometer_end,
            distance=distance,
            fuel_added=row.fuel_added,
        ))
    return result


# ---------------------------------------------------------------------------
# Management Reporting Endpoints
# ---------------------------------------------------------------------------

@router.get("/no-shows")
def get_no_shows(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Return walkers marked as no-shows for a given date (default today).

    Each entry includes walker name, driver name, and the date.
    """
    if target_date is None:
        target_date = date.today()

    rows = (
        db.query(WalkerRating)
        .filter(
            WalkerRating.date == target_date,
            WalkerRating.present == False,
        )
        .all()
    )

    emp_ids = {r.walker_id for r in rows} | {r.driver_id for r in rows}
    emp_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}

    result = []
    for row in rows:
        walker = emp_map.get(row.walker_id)
        driver = emp_map.get(row.driver_id)
        result.append({
            "walker_id": str(row.walker_id),
            "walker_name": walker.name if walker else "Unknown",
            "driver_name": driver.name if driver else "Unknown",
            "date": row.date.isoformat(),
        })
    return result


@router.get("/walker-stats")
def get_walker_stats(
    week_start: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Return per-walker attendance and rating summary for a 7-day window.

    week_start defaults to the most recent Monday. Each entry includes
    presence rate, average stars (excluding no-shows), and no-show count.
    """
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # most recent Monday
    week_end = week_start + timedelta(days=6)

    rows = (
        db.query(WalkerRating)
        .filter(
            WalkerRating.date >= week_start,
            WalkerRating.date <= week_end,
        )
        .all()
    )

    # Bulk-fetch all referenced walkers up front
    walker_ids = {r.walker_id for r in rows}
    emp_map    = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(walker_ids)).all()}

    # Group by walker_id
    walker_data: dict = {}
    for row in rows:
        wid = str(row.walker_id)
        if wid not in walker_data:
            walker = emp_map.get(row.walker_id)
            walker_data[wid] = {
                "walker_id": wid,
                "walker_name": walker.name if walker else "Unknown",
                "total_shifts": 0,
                "present_shifts": 0,
                "no_show_count": 0,
                "stars_total": 0,
                "rated_shifts": 0,
            }
        entry = walker_data[wid]
        entry["total_shifts"] += 1
        if row.present:
            entry["present_shifts"] += 1
            if row.stars is not None:
                entry["stars_total"] += row.stars
                entry["rated_shifts"] += 1
        else:
            entry["no_show_count"] += 1

    result = []
    for entry in walker_data.values():
        avg_stars = (
            round(entry["stars_total"] / entry["rated_shifts"], 2)
            if entry["rated_shifts"] > 0 else None
        )
        presence_rate = (
            round(entry["present_shifts"] / entry["total_shifts"] * 100, 1)
            if entry["total_shifts"] > 0 else None
        )
        result.append({
            "walker_id": entry["walker_id"],
            "walker_name": entry["walker_name"],
            "total_shifts": entry["total_shifts"],
            "present_shifts": entry["present_shifts"],
            "no_show_count": entry["no_show_count"],
            "presence_rate": presence_rate,
            "avg_stars": avg_stars,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        })

    result.sort(key=lambda x: (x["no_show_count"], -(x["avg_stars"] or 0)), reverse=True)
    return result


@router.get("/inspections/history")
def get_inspections_history(
    days: int = Query(30, ge=1, le=365),
    driver_id: Optional[UUID] = Query(None),
    truck_id: Optional[UUID] = Query(None),
    has_failures: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Return full inspection records for the last N days.

    Filterable by driver, truck, and pass/fail status.
    Returns driver name, truck name, date, submitted_at, has_failures, and per-item results.
    """
    since = date.today() - timedelta(days=days - 1)

    q = db.query(VehicleInspection).filter(VehicleInspection.date >= since)
    if driver_id is not None:
        q = q.filter(VehicleInspection.driver_id == driver_id)
    if truck_id is not None:
        q = q.filter(VehicleInspection.truck_id == truck_id)
    if has_failures is not None:
        q = q.filter(VehicleInspection.has_failures == has_failures)

    rows = q.order_by(VehicleInspection.date.desc(), VehicleInspection.submitted_at.desc()).all()

    emp_ids   = {r.driver_id for r in rows}
    truck_ids = {r.truck_id for r in rows if r.truck_id}
    emp_map   = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    return [
        {
            "inspection_id": str(row.id),
            "driver_id": str(row.driver_id),
            "driver_name": emp_map[row.driver_id].name if row.driver_id in emp_map else "Unknown",
            "truck_id": str(row.truck_id) if row.truck_id else None,
            "truck_name": truck_map[row.truck_id].name if row.truck_id and row.truck_id in truck_map else None,
            "date": row.date.isoformat(),
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "has_failures": row.has_failures,
            "failed_items": [k for k, v in row.items.items() if v is False],
            "passed_items": [k for k, v in row.items.items() if v is True],
            "notes": row.notes,
        }
        for row in rows
    ]


def _walker_grade(presence_rate, avg_stars):
    """Compute letter grade from presence rate (0-100) and avg stars (0-5)."""
    p = (presence_rate or 0) / 100
    s = (avg_stars or 0) / 5.0
    combined = p * 0.5 + s * 0.5
    if combined >= 0.90: return "A"
    if combined >= 0.75: return "B"
    if combined >= 0.60: return "C"
    if combined >= 0.45: return "D"
    return "F"


@router.get("/walker-leaderboard")
def get_walker_leaderboard(
    min_shifts: int = Query(1, ge=1, le=50, description="Minimum shifts before a grade is assigned"),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """All-time performance summary for every active walker.

    Returns presence rate, avg stars, total shifts, no-show count, and a
    computed letter grade (A–F) for each walker. Walkers with fewer than
    min_shifts total shifts receive grade=null and grade_eligible=false.

    Grade formula (weighted):
      presence_score  = presence_rate / 100              (weight 0.5)
      star_score      = avg_stars / 5.0                  (weight 0.5, 0 if no ratings)
      combined        = presence_score * 0.5 + star_score * 0.5
      A ≥ 0.90, B ≥ 0.75, C ≥ 0.60, D ≥ 0.45, F < 0.45
    """
    walkers = (
        db.query(Employee)
        .filter(Employee.role == "walker", Employee.is_active == True)
        .order_by(Employee.name)
        .all()
    )

    walker_ids = [w.id for w in walkers]
    rows = db.query(WalkerRating).filter(WalkerRating.walker_id.in_(walker_ids)).all()

    # Aggregate per walker
    agg: dict = {str(w.id): {
        "walker_id": str(w.id),
        "walker_name": w.name,
        "total_shifts": 0, "present_shifts": 0, "no_show_count": 0,
        "stars_total": 0, "rated_shifts": 0,
    } for w in walkers}

    for row in rows:
        wid = str(row.walker_id)
        if wid not in agg:
            continue
        e = agg[wid]
        e["total_shifts"] += 1
        if row.present:
            e["present_shifts"] += 1
            if row.stars is not None:
                e["stars_total"] += row.stars
                e["rated_shifts"] += 1
        else:
            e["no_show_count"] += 1

    result = []
    for e in agg.values():
        avg_stars = round(e["stars_total"] / e["rated_shifts"], 2) if e["rated_shifts"] > 0 else None
        presence_rate = round(e["present_shifts"] / e["total_shifts"] * 100, 1) if e["total_shifts"] > 0 else None
        grade_eligible = e["total_shifts"] >= min_shifts
        result.append({
            **e,
            "avg_stars": avg_stars,
            "presence_rate": presence_rate,
            "grade_eligible": grade_eligible,
            "grade": _walker_grade(presence_rate, avg_stars) if grade_eligible else None,
        })

    result.sort(key=lambda x: (x["grade"] or "Z", -(x["avg_stars"] or 0)))
    return result


@router.get("/walker-profile/{walker_id}")
def get_walker_profile(
    walker_id: UUID,
    start_date: Optional[date] = Query(None, description="Filter ratings from this date (inclusive)"),
    end_date: Optional[date] = Query(None, description="Filter ratings up to this date (inclusive)"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """All-time stats + rating history for one walker, with driver names and comments.

    Walkers may fetch their own profile; management/admin may fetch any.
    All-time KPIs (total_shifts, grade, etc.) always reflect the full history.
    The ratings list is filtered by start_date/end_date when provided.
    """
    assert_owns_or_privileged(caller, walker_id, "performance profile")
    walker = db.query(Employee).filter(Employee.id == walker_id).first()
    if not walker:
        raise HTTPException(status_code=404, detail="Walker not found.")

    # Full history for KPI computation
    all_rows = (
        db.query(WalkerRating)
        .filter(WalkerRating.walker_id == walker_id)
        .order_by(WalkerRating.date.desc())
        .all()
    )

    # Filtered rows for the ratings list
    filtered_rows = all_rows
    if start_date:
        filtered_rows = [r for r in filtered_rows if r.date >= start_date]
    if end_date:
        filtered_rows = [r for r in filtered_rows if r.date <= end_date]

    driver_ids = {r.driver_id for r in all_rows}
    driver_map = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(driver_ids)).all()}

    total = len(all_rows)
    present = sum(1 for r in all_rows if r.present)
    no_shows = total - present
    rated = [r for r in all_rows if r.present and r.stars is not None]
    avg_stars = round(sum(r.stars for r in rated) / len(rated), 2) if rated else None
    presence_rate = round(present / total * 100, 1) if total > 0 else None

    ratings_out = []
    for r in filtered_rows:
        drv = driver_map.get(r.driver_id)
        ratings_out.append({
            "id": str(r.id),
            "date": r.date.isoformat(),
            "driver_id": str(r.driver_id),
            "driver_name": drv.name if drv else "Unknown",
            "present": r.present,
            "stars": r.stars,
            "comment": r.comment,
            "rated_at": r.rated_at.isoformat() if r.rated_at else None,
        })

    return {
        "walker_id": str(walker.id),
        "walker_name": walker.name,
        "total_shifts": total,
        "present_shifts": present,
        "no_show_count": no_shows,
        "avg_stars": avg_stars,
        "presence_rate": presence_rate,
        "grade": _walker_grade(presence_rate, avg_stars) if total > 0 else None,
        "ratings": ratings_out,
    }


@router.get("/walker-consistency/{walker_id}")
def get_walker_consistency(
    walker_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Per-driver rating breakdown for a walker.

    Returns each driver's avg stars for this walker, the walker's overall avg,
    and a deviation score. Drivers deviating ≥1.0 star from the walker's mean
    are flagged — this can signal driver bias rather than genuine walker quality variation.
    """
    walker = db.query(Employee).filter(Employee.id == walker_id).first()
    if not walker:
        raise HTTPException(status_code=404, detail="Walker not found.")

    rows = (
        db.query(WalkerRating)
        .filter(WalkerRating.walker_id == walker_id, WalkerRating.present == True, WalkerRating.stars.isnot(None))
        .all()
    )

    if not rows:
        return {"walker_avg_stars": None, "drivers": [], "flag_threshold": 1.0}

    # Group by driver
    from collections import defaultdict
    driver_buckets: dict = defaultdict(list)
    for r in rows:
        driver_buckets[str(r.driver_id)].append(r.stars)

    driver_ids = list(driver_buckets.keys())
    from uuid import UUID as _UUID
    driver_map = {
        str(e.id): e.name
        for e in db.query(Employee).filter(Employee.id.in_([_UUID(d) for d in driver_ids])).all()
    }

    overall_stars = [r.stars for r in rows]
    walker_avg = round(sum(overall_stars) / len(overall_stars), 2)

    FLAG_THRESHOLD = 1.0
    drivers_out = []
    for did, stars_list in driver_buckets.items():
        avg = round(sum(stars_list) / len(stars_list), 2)
        deviation = round(avg - walker_avg, 2)
        drivers_out.append({
            "driver_id": did,
            "driver_name": driver_map.get(did, "Unknown"),
            "shift_count": len(stars_list),
            "avg_stars": avg,
            "deviation": deviation,
            "flagged": abs(deviation) >= FLAG_THRESHOLD,
        })

    # Sort by most extreme deviation first
    drivers_out.sort(key=lambda x: abs(x["deviation"]), reverse=True)

    return {
        "walker_avg_stars": walker_avg,
        "drivers": drivers_out,
        "flag_threshold": FLAG_THRESHOLD,
    }


@router.get("/inspection-failures/summary")
def get_inspection_failure_summary(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
):
    """Return inspection failure counts per item key over the last N days (default 7).

    Useful for the vehicle compliance panel to spot recurring mechanical issues.
    """
    since = date.today() - timedelta(days=days - 1)

    rows = (
        db.query(VehicleInspection)
        .filter(
            VehicleInspection.date >= since,
            VehicleInspection.has_failures == True,
        )
        .all()
    )

    failure_counts: dict = {k: 0 for k in INSPECTION_ITEMS}
    total_inspections = db.query(VehicleInspection).filter(VehicleInspection.date >= since).count()

    for row in rows:
        for key, passed in row.items.items():
            if passed is False and key in failure_counts:
                failure_counts[key] += 1

    result = [
        {
            "item": key,
            "label": key.replace("_", " ").title(),
            "failure_count": count,
            "failure_rate": round(count / total_inspections * 100, 1) if total_inspections > 0 else 0,
        }
        for key, count in failure_counts.items()
        if count > 0
    ]
    result.sort(key=lambda x: x["failure_count"], reverse=True)

    return {
        "days": days,
        "since": since.isoformat(),
        "total_inspections": total_inspections,
        "failures": result,
    }
