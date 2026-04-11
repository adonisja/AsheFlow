from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.field_ops import CheckIn, Departure, WalkerRating, VehicleInspection, FuelMileageLog, INSPECTION_ITEMS
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.truck import Truck
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
    """Return crew members on the same truck as employee_id for target_date (today if omitted)."""
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
    # Fix #2: caller can only check in themselves
    if payload.employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only check in yourself.")

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
    return db.query(CheckIn).filter(CheckIn.employee_id == employee_id).order_by(CheckIn.date.desc()).all()


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

    result = []
    for row in rows:
        emp = db.query(Employee).filter(Employee.id == row.employee_id).first()
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

    if payload.present and (payload.stars is None or not (1 <= payload.stars <= 5)):
        raise HTTPException(status_code=400, detail="Stars must be between 1 and 5 for present walkers.")
    if not payload.present and payload.stars is not None:
        raise HTTPException(status_code=400, detail="Stars should not be provided for a no-show.")

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

    result = []
    for row in rows:
        emp = db.query(Employee).filter(Employee.id == row.driver_id).first()
        truck = db.query(Truck).filter(Truck.id == row.truck_id).first() if row.truck_id else None
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

    result = []
    for row in rows:
        emp = db.query(Employee).filter(Employee.id == row.driver_id).first()
        truck = db.query(Truck).filter(Truck.id == row.truck_id).first() if row.truck_id else None
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

    result = []
    for row in rows:
        walker = db.query(Employee).filter(Employee.id == row.walker_id).first()
        driver = db.query(Employee).filter(Employee.id == row.driver_id).first()
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

    # Group by walker_id
    walker_data: dict = {}
    for row in rows:
        wid = str(row.walker_id)
        if wid not in walker_data:
            walker = db.query(Employee).filter(Employee.id == row.walker_id).first()
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
