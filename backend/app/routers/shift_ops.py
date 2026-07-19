from datetime import date, datetime, timezone
from app.services.local_date import company_today
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, assert_owns_or_privileged
from app.models.employee import Employee
from app.models.field_ops import Departure
from app.models.notification import Notification
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.models.crew_compliance import CrewCompliance
from app.models.driver_check_in import DriverCheckIn
from app.models.rts_clearance import RTSReport, StationHandoff, RTS_REPORT_STATUSES
from app.models.rts import MissingPackage
from app.services.audit import write_audit
from app.schemas.shift_ops import (
    CrewComplianceCreate, CrewComplianceResponse,
    DriverCheckInCreate, DriverCheckInResponse,
    RTSReportCreate, RTSReportReview, RTSReportResponse,
    StationHandoffCreate, StationHandoffResponse,
)

router = APIRouter(prefix="/shift-ops", tags=["shift-ops"])

allow_driver      = RoleChecker(["driver"])
allow_management  = RoleChecker(["dispatch", "management", "admin"])


# ---------------------------------------------------------------------------
# Crew Compliance (driver submits AP arrival compliance for their crew)
# ---------------------------------------------------------------------------

@router.post("/crew-compliance", response_model=List[CrewComplianceResponse], status_code=status.HTTP_201_CREATED)
def submit_crew_compliance(
    payload: CrewComplianceCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit AP compliance records for the driver's crew.

    One call covers all crew members. The driver can only submit for their own crew.
    Duplicate entries (same employee_id for the same date) return 400 — use the
    management override endpoint to correct records after submission.
    """
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit compliance for your own crew.")

    # Verify at least one crew member is on the same truck
    member_row = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == payload.driver_id,
            AssignmentMember.company_id == caller.company_id,
            TruckAssignment.date == payload.date,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if not member_row:
        raise HTTPException(status_code=400, detail="No truck assignment found for this driver on this date.")

    crew_member_ids = {
        str(am.employee_id)
        for am in db.query(AssignmentMember)
        .filter(
            AssignmentMember.assignment_id == member_row.assignment_id,
            AssignmentMember.company_id == caller.company_id,
        )
        .all()
    }

    created = []
    for entry in payload.entries:
        if str(entry.employee_id) not in crew_member_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Employee {entry.employee_id} is not on your truck assignment for this date.",
            )

        existing = db.query(CrewCompliance).filter(
            CrewCompliance.driver_id == payload.driver_id,
            CrewCompliance.employee_id == entry.employee_id,
            CrewCompliance.date == payload.date,
            CrewCompliance.company_id == caller.company_id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Compliance already recorded for employee {entry.employee_id} on {payload.date}.",
            )

        row = CrewCompliance(
            company_id=caller.company_id,   # NOT NULL — was omitted (IntegrityError 500)
            driver_id=payload.driver_id,
            employee_id=entry.employee_id,
            date=payload.date,
            arrival_time=entry.arrival_time,
            uniform_pass=entry.uniform_pass,
            cart_cover_pass=entry.cart_cover_pass,
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)
    return created


@router.get("/crew-compliance/summary/{target_date}")
def get_crew_compliance_summary(
    target_date: date,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all compliance records for a date with employee names. Management use."""
    rows = (
        db.query(CrewCompliance)
        .filter(
            CrewCompliance.date == target_date,
            CrewCompliance.company_id == caller.company_id,
        )
        .order_by(CrewCompliance.submitted_at.asc())
        .all()
    )

    emp_ids = {r.driver_id for r in rows} | {r.employee_id for r in rows}
    emp_map = {
        e.id: e
        for e in db.query(Employee)
        .filter(Employee.id.in_(emp_ids), Employee.company_id == caller.company_id)
        .all()
    }

    return [
        {
            "driver_name": emp_map[r.driver_id].name if r.driver_id in emp_map else "Unknown",
            "employee_id": str(r.employee_id),
            "employee_name": emp_map[r.employee_id].name if r.employee_id in emp_map else "Unknown",
            "arrival_time": r.arrival_time.isoformat() if r.arrival_time else None,
            "uniform_pass": r.uniform_pass,
            "cart_cover_pass": r.cart_cover_pass,
        }
        for r in rows
    ]


@router.get("/crew-compliance/{driver_id}", response_model=List[CrewComplianceResponse])
def get_crew_compliance(
    driver_id: UUID,
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return compliance records submitted by a driver, optionally for a single date."""
    assert_owns_or_privileged(caller, driver_id, "crew compliance")
    q = db.query(CrewCompliance).filter(CrewCompliance.driver_id == driver_id)
    if target_date:
        q = q.filter(CrewCompliance.date == target_date)
    return q.order_by(CrewCompliance.date.desc()).all()


# ---------------------------------------------------------------------------
# Driver Check-Ins (4 per shift)
# ---------------------------------------------------------------------------

@router.post("/check-in", response_model=DriverCheckInResponse, status_code=status.HTTP_201_CREATED)
def submit_driver_check_in(
    payload: DriverCheckInCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit a mid-shift check-in. Four allowed per driver per date (numbers 1–4).

    Requires a departure record for the same date — driver must have departed first.
    """
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit your own check-ins.")

    departure = db.query(Departure).filter(
        Departure.employee_id == payload.driver_id,
        Departure.date == payload.date,
        Departure.company_id == caller.company_id,
    ).first()
    if not departure:
        raise HTTPException(status_code=400, detail="Mid-shift check-ins require a departure record for today.")

    existing = db.query(DriverCheckIn).filter(
        DriverCheckIn.driver_id == payload.driver_id,
        DriverCheckIn.date == payload.date,
        DriverCheckIn.check_in_number == payload.check_in_number,
        DriverCheckIn.company_id == caller.company_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Check-in #{payload.check_in_number} already submitted for today.",
        )

    # company_id is NOT NULL on DriverCheckIn but absent from the payload — set it
    # from the caller (was an IntegrityError 500 on every check-in submit).
    row = DriverCheckIn(**payload.model_dump(), company_id=caller.company_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/check-in/{driver_id}", response_model=List[DriverCheckInResponse])
def get_driver_check_ins(
    driver_id: UUID,
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all check-ins for a driver, optionally filtered to a single date."""
    assert_owns_or_privileged(caller, driver_id, "check-ins")
    q = db.query(DriverCheckIn).filter(DriverCheckIn.driver_id == driver_id)
    if target_date:
        q = q.filter(DriverCheckIn.date == target_date)
    return q.order_by(DriverCheckIn.date.desc(), DriverCheckIn.check_in_number.asc()).all()


@router.get("/check-ins/summary")
def get_check_ins_summary(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
    caller: Employee = Depends(get_caller_employee),
):
    """Return latest check-in per driver for a date. Shows which drivers need support."""
    if target_date is None:
        target_date = company_today(db, caller.company_id)

    rows = (
        db.query(DriverCheckIn)
        .filter(
            DriverCheckIn.date == target_date,
            DriverCheckIn.company_id == caller.company_id,
        )
        .order_by(DriverCheckIn.driver_id, DriverCheckIn.check_in_number.desc())
        .all()
    )

    driver_ids = {r.driver_id for r in rows}
    emp_map = {
        e.id: e
        for e in db.query(Employee)
        .filter(Employee.id.in_(driver_ids), Employee.company_id == caller.company_id)
        .all()
    }

    # Latest check-in per driver
    seen: set = set()
    result = []
    for row in rows:
        if row.driver_id in seen:
            continue
        seen.add(row.driver_id)
        result.append({
            "driver_id": str(row.driver_id),
            "driver_name": emp_map[row.driver_id].name if row.driver_id in emp_map else "Unknown",
            "latest_check_in": row.check_in_number,
            "routes_remaining": row.routes_remaining,
            "help_requested": row.help_requested,
            "working_crew_count": row.working_crew_count,
            "ncns_count": row.ncns_count,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        })

    result.sort(key=lambda x: (x["help_requested"], -x["routes_remaining"]), reverse=True)
    return result


# ---------------------------------------------------------------------------
# RTS Report (field — dispatch approval gate before leaving the AP area)
# ---------------------------------------------------------------------------

@router.post("/rts-report", response_model=RTSReportResponse, status_code=status.HTTP_201_CREATED)
def submit_rts_report(
    payload: RTSReportCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit the field RTS report before leaving the anchor point area.

    Driver confirms all crew are back on the truck and lists every undelivered
    package grouped by reason. Dispatch reviews and approves or rejects.
    The driver is gated — they may not leave the field until status='approved'.
    """
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit your own RTS report.")

    existing = db.query(RTSReport).filter(
        RTSReport.company_id == caller.company_id,
        RTSReport.driver_id == payload.driver_id,
        RTSReport.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="RTS report already submitted for today.")

    packages_data = [e.model_dump() for e in payload.rts_packages]
    total_rts = sum(e.count for e in payload.rts_packages)

    row = RTSReport(
        company_id=caller.company_id,
        driver_id=payload.driver_id,
        date=payload.date,
        crew_confirmed=payload.crew_confirmed,
        rts_packages=packages_data,
        total_rts=total_rts,
        status="pending",
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="rts_report.submit",
        target_table="rts_reports",
        target_id=str(row.id),
        detail={"date": str(payload.date), "total_rts": total_rts, "crew_confirmed": payload.crew_confirmed},
    )

    dispatch_recipients = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(["dispatch", "management", "admin"]),
        Employee.is_active == True,
    ).all()
    rts_summary = f"{total_rts} package(s)" if total_rts else "no undelivered packages"
    for recipient in dispatch_recipients:
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=recipient.id,
            type="rts_submitted",
            message=(
                f"{caller.name} submitted an RTS report for {payload.date} "
                f"({rts_summary}). Crew confirmed: {'yes' if payload.crew_confirmed else 'no'}. "
                f"Awaiting your approval to release the driver."
            ),
        ))

    db.commit()
    db.refresh(row)
    return row


@router.patch("/rts-report/{driver_id}", response_model=RTSReportResponse)
def review_rts_report(
    driver_id: UUID,
    payload: RTSReportReview,
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
    caller: Employee = Depends(get_caller_employee),
):
    """Approve or reject an RTS report. Dispatch/management only.

    Approving clears the driver to head back to the station.
    Rejecting holds the driver in the field — dispatch_notes should explain why.
    """
    if target_date is None:
        target_date = company_today(db, caller.company_id)

    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'.")

    row = db.query(RTSReport).filter(
        RTSReport.driver_id == driver_id,
        RTSReport.date == target_date,
        RTSReport.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No RTS report found for this driver.")

    if row.status != "pending":
        raise HTTPException(status_code=400, detail=f"RTS report is already {row.status}.")

    row.status = payload.status
    row.dispatch_notes = payload.dispatch_notes
    row.reviewed_by = caller.id
    row.reviewed_by_name = caller.name
    row.reviewed_at = datetime.now(timezone.utc)
    write_audit(
        db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type=f"rts_report.{payload.status}",
        target_table="rts_reports",
        target_id=str(row.id),
        detail={"date": str(target_date), "driver_id": str(driver_id)},
    )

    driver = db.query(Employee).filter(
        Employee.id == driver_id,
        Employee.company_id == caller.company_id,
    ).first()
    if driver:
        if payload.status == "approved":
            driver_message = (
                f"Your RTS report for {target_date} has been approved. "
                f"You are cleared to return to the station."
            )
        else:
            notes_suffix = f" Dispatch notes: {payload.dispatch_notes}" if payload.dispatch_notes else ""
            driver_message = (
                f"Your RTS report for {target_date} was not approved.{notes_suffix} "
                f"Contact dispatch for further instructions."
            )
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=driver.id,
            type=f"rts_{payload.status}",
            message=driver_message,
        ))

    # On approval (return confirmed), auto-close the day for any crew still on the
    # truck who were never marked off — the run is over, so still-active members
    # are done for the day. Scoped to the driver's own assignment for the date,
    # company-scoped, driver excluded. Idempotent: only flips status='active' rows.
    if payload.status == "approved":
        driver_member = db.query(AssignmentMember).join(
            TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id,
        ).filter(
            AssignmentMember.employee_id == driver_id,
            AssignmentMember.company_id == caller.company_id,
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == caller.company_id,
        ).first()
        if driver_member:
            now = datetime.now(timezone.utc)
            unmarked = db.query(AssignmentMember).filter(
                AssignmentMember.assignment_id == driver_member.assignment_id,
                AssignmentMember.company_id == caller.company_id,
                AssignmentMember.employee_id != driver_id,
                AssignmentMember.status == "active",
            ).all()
            for am in unmarked:
                am.status = "departed"
                am.departed_at = now
            if unmarked:
                write_audit(
                    db,
                    company_id=str(caller.company_id),
                    actor_id=str(caller.id),
                    action_type="crew.auto_departed_on_return",
                    target_table="assignment_members",
                    target_id=str(driver_member.assignment_id),
                    detail={"date": str(target_date), "count": len(unmarked),
                            "trigger": "rts_report.approved"},
                )

    db.commit()
    db.refresh(row)
    return row


@router.get("/rts-report/{driver_id}", response_model=RTSReportResponse)
def get_rts_report(
    driver_id: UUID,
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the RTS report for a driver on a given date (default today)."""
    assert_owns_or_privileged(caller, driver_id, "RTS report")

    if target_date is None:
        target_date = company_today(db, caller.company_id)

    row = db.query(RTSReport).filter(
        RTSReport.driver_id == driver_id,
        RTSReport.date == target_date,
        RTSReport.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No RTS report found.")
    return row


@router.get("/rts-reports/pending")
def get_pending_rts_reports(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
):
    """Return all pending RTS reports for a date. Dispatch review queue."""
    if target_date is None:
        target_date = company_today(db, caller.company_id)

    rows = (
        db.query(RTSReport)
        .filter(
            RTSReport.date == target_date,
            RTSReport.status == "pending",
            RTSReport.company_id == caller.company_id,
        )
        .order_by(RTSReport.submitted_at.asc())
        .all()
    )

    driver_ids = {r.driver_id for r in rows}
    emp_map = {
        e.id: e
        for e in db.query(Employee).filter(
            Employee.id.in_(driver_ids),
            Employee.company_id == caller.company_id,
        ).all()
    }

    return [
        {
            "report_id": str(r.id),
            "driver_id": str(r.driver_id),
            "driver_name": emp_map[r.driver_id].name if r.driver_id in emp_map else "Unknown",
            "crew_confirmed": r.crew_confirmed,
            "total_rts": r.total_rts,
            "rts_packages": r.rts_packages,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Station Handoff (physical return at the station — closes the loop)
# ---------------------------------------------------------------------------

@router.post("/station-handoff", response_model=StationHandoffResponse, status_code=status.HTTP_201_CREATED)
def submit_station_handoff(
    payload: StationHandoffCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_driver),
    caller: Employee = Depends(get_caller_employee),
):
    """Confirm physical handoff at the station — totes returned, RTS scanned back in.

    Requires the driver's RTS report for the same date to be approved first.
    This is the final closing record for the return leg of the shift.
    """
    if payload.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit your own station handoff.")

    rts_report = db.query(RTSReport).filter(
        RTSReport.company_id == caller.company_id,
        RTSReport.driver_id == payload.driver_id,
        RTSReport.date == payload.date,
    ).first()
    if not rts_report:
        raise HTTPException(
            status_code=400,
            detail="No RTS report found for today. Submit your field RTS report first.",
        )
    if rts_report.status != "approved":
        raise HTTPException(
            status_code=400,
            detail="Your RTS report has not been approved by dispatch yet.",
        )

    existing = db.query(StationHandoff).filter(
        StationHandoff.company_id == caller.company_id,
        StationHandoff.driver_id == payload.driver_id,
        StationHandoff.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Station handoff already recorded for today.")

    # missing_count is computed, not typed: unresolved MissingPackage rows across
    # the driver's truck assignment for the date (ADR-193 D5).
    ta = (
        db.query(TruckAssignment)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == payload.date,
            AssignmentMember.employee_id == caller.id,
        )
        .first()
    )
    missing_count = 0
    if ta is not None:
        missing_count = (
            db.query(MissingPackage)
            .filter(
                MissingPackage.company_id == caller.company_id,
                MissingPackage.truck_assignment_id == ta.id,
                MissingPackage.resolution_status == "unresolved",
            )
            .count()
        )

    row = StationHandoff(
        company_id=caller.company_id,
        driver_id=payload.driver_id,
        date=payload.date,
        totes_returned=payload.totes_returned,
        rts_count=payload.rts_count,
        missing_count=missing_count,
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="station_handoff.submit",
        target_table="station_handoffs",
        target_id=str(row.id),
        detail={
            "date": str(payload.date),
            "totes_returned": payload.totes_returned,
            "rts_count": payload.rts_count,
            "missing_count": missing_count,
        },
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/station-handoff/{driver_id}", response_model=StationHandoffResponse)
def get_station_handoff(
    driver_id: UUID,
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return the station handoff record for a driver on a given date (default today)."""
    assert_owns_or_privileged(caller, driver_id, "station handoff")

    if target_date is None:
        target_date = company_today(db, caller.company_id)

    row = db.query(StationHandoff).filter(
        StationHandoff.driver_id == driver_id,
        StationHandoff.date == target_date,
        StationHandoff.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No station handoff found.")
    return row


@router.get("/station-handoffs/summary")
def get_station_handoffs_summary(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all station handoffs for a date. Management overview of returned totes and RTS."""
    if target_date is None:
        target_date = company_today(db, caller.company_id)

    rows = (
        db.query(StationHandoff)
        .filter(
            StationHandoff.date == target_date,
            StationHandoff.company_id == caller.company_id,
        )
        .order_by(StationHandoff.submitted_at.asc())
        .all()
    )

    driver_ids = {r.driver_id for r in rows}
    emp_map = {
        e.id: e
        for e in db.query(Employee)
        .filter(Employee.id.in_(driver_ids), Employee.company_id == caller.company_id)
        .all()
    }

    return {
        "date": target_date.isoformat(),
        "total_totes_returned": sum(r.totes_returned for r in rows),
        "total_rts_returned": sum(r.rts_count for r in rows),
        "drivers": [
            {
                "driver_id": str(r.driver_id),
                "driver_name": emp_map[r.driver_id].name if r.driver_id in emp_map else "Unknown",
                "totes_returned": r.totes_returned,
                "rts_count": r.rts_count,
                "notes": r.notes,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in rows
        ],
    }
