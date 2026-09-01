"""Manual RTS / missing / damaged entry for workforce mode (ADR-292).

    POST /manual-returns/scan-label       read a TBA off a photographed label (D4)
    POST /manual-returns/rts              record an undelivered package
    POST /manual-returns/missing          record a package that never arrived
    POST /manual-returns/damaged          record a damaged package
    GET  /manual-returns/{route_date}     the day's records, for the EOD handoff

THE TBA IS REAL (D1). In workforce mode the tracking number is still printed on
the package in the walker's hand — what is missing is the MANIFEST to match it
against, not the identifier. So these write the same `RTSPackage`,
`MissingPackage` and `DamagedPackage` rows full mode writes, with `source`
marking provenance and the manifest check skipped.

NOTHING IS SYNTHESISED (D2). A generated id like `WF-2026-08-24-001` would be
unusable outside AsheFlow: Amazon can only act on a real TBA, which is what
makes a scorecard appeal answerable and a future reconciliation possible. That
is the opposite call from ADR-291's route adapter, which DOES mint ids — because
there the thing being identified (a captain-entered address) has no Amazon
identity at all, while here it does.

GATED TO WORKFORCE MODE. `rts.py` is gated to `full` and carries 394 package
references' worth of manifest coupling; this is the small mirror, not an
un-gating of that.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.employee import Employee
from app.models.rts import (
    DamagedPackage, MissingPackage, RTSPackage, is_reattemptable,
)
from app.models.walker_route import Route
from app.services.audit import write_audit
from app.services.constants import ROUTE_LEAD_ROLES
from app.services.note_scrub import scrub_note

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manual-returns", tags=["manual-returns"])

# D-audit dim 2: the CAPTAIN operationally records these as walkers return, with
# the driver as fallback and dispatch above for correction.
#
# `walker` is deliberately absent. A walker reporting their own non-delivery
# unsupervised is the failure the captain-confirms model exists to prevent —
# every one of these records is an exception to a delivery that did not happen,
# and self-reporting them is how a bad day becomes an invisible one.
_allow_record = RoleChecker(list(ROUTE_LEAD_ROLES))
_allow_read = RoleChecker(list(ROUTE_LEAD_ROLES))

# A shipping label photo. 8 MB is generous for a phone camera and rejects a
# mis-selected video before Textract is billed for it.
_MAX_LABEL_BYTES = 8 * 1024 * 1024
_IMAGE_EXTS = {"jpg", "jpeg", "png", "pdf"}


# ── request schemas (dim 9) ───────────────────────────────────────────────────

class _PackageRecordIn(BaseModel):
    """Fields every manual record shares."""
    model_config = ConfigDict(extra="forbid")

    route_id: UUID
    # A real Amazon TBA (D1/D2). Bounded to the column width; not format-checked
    # beyond that, because a captain correcting a scanner misread must not be
    # blocked by a regex when the physical label is right there.
    tba_number: str = Field(..., min_length=4, max_length=50)


class RTSRecordIn(_PackageRecordIn):
    # Literal, not a free string: rts_type drives is_reattemptable, which drives
    # whether the package can go out again today.
    rts_type: Literal[
        "no_access", "business_closed", "package_damaged",
        "inclement_weather", "customer_requested_future_delivery",
        "customer_cancelled_order",
    ]
    rts_explanation: str = Field(..., min_length=1, max_length=1000)


class MissingRecordIn(_PackageRecordIn):
    notes: Optional[str] = Field(None, max_length=1000)


class DamagedRecordIn(_PackageRecordIn):
    stage: Literal["station", "route"]
    damage_notes: str = Field(..., min_length=1, max_length=1000)


# ── response schemas ──────────────────────────────────────────────────────────

class LabelReadOut(BaseModel):
    """What the scanner thinks is on the label. Always confirmed by a human."""
    tba: Optional[str] = None
    confidence: Optional[float] = None
    lines: list[str] = []
    warnings: list[str] = []
    needs_manual_entry: bool = True


class ManualRecordOut(BaseModel):
    id: UUID
    tba_number: str
    route_id: UUID
    source: str
    kind: str                      # rts | missing | damaged
    is_reattemptable: Optional[bool] = None
    recorded_by_name: Optional[str] = None


class DayReturnsOut(BaseModel):
    rts: list[ManualRecordOut]
    missing: list[ManualRecordOut]
    damaged: list[ManualRecordOut]
    total: int


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_route(db: Session, caller: Employee, route_id: UUID) -> Route:
    """The route must belong to this company (dim 1) and this day's work."""
    route = (
        db.query(Route)
        .filter(Route.id == route_id, Route.company_id == caller.company_id)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")
    return route


def _executor(db: Session, company_id: UUID, route: Route):
    """The walker of record for a route, or None. Resolved through the
    participant join rather than a denormalised name (ADR-212)."""
    from app.models.walker_route import RouteParticipant

    row = (
        db.query(Employee)
        .join(RouteParticipant, RouteParticipant.employee_id == Employee.id)
        .filter(
            RouteParticipant.route_id == route.id,
            RouteParticipant.company_id == company_id,
            RouteParticipant.role == "executor",
        )
        .first()
    )
    return row


def _reject_duplicate(db: Session, model, company_id: UUID, route_id: UUID,
                      tba: str, label: str) -> None:
    """One record per package per route.

    A captain working through a returned tote can easily scan the same label
    twice. Without this the second scan silently doubles the day's RTS count,
    which lands in the scorecard cross-check as a real discrepancy.
    """
    exists = (
        db.query(model)
        .filter(
            model.company_id == company_id,
            model.route_id == route_id,
            model.tba_number == tba,
        )
        .first()
    )
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{tba} is already recorded as {label} on this route.",
        )


def _reject_damaged_duplicate(db: Session, company_id: UUID, route: Route,
                              tba: str) -> None:
    """DamagedPackage has no route_id, so uniqueness is per truck-day."""
    exists = (
        db.query(DamagedPackage)
        .filter(
            DamagedPackage.company_id == company_id,
            DamagedPackage.route_date == route.route_date,
            DamagedPackage.truck_assignment_id == route.truck_assignment_id,
            DamagedPackage.tba_number == tba,
        )
        .first()
    )
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{tba} is already recorded as damaged on this truck today.",
        )


# ── label scan (D4) ───────────────────────────────────────────────────────────

@router.post("/scan-label", response_model=LabelReadOut)
async def scan_label(
    file: UploadFile = File(...),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_record),
    db: Session = Depends(get_db),
):
    """Read the TBA off a photographed shipping label. **Writes nothing.**

    D4: reuses `label_ingestor` (ADR-246) rather than a second OCR path. It
    already extracts a TBA with per-line confidence and documents why the read
    must be confirmed — OCR on a creased label in a dim van is exactly where a
    misread becomes a phantom record.

    Only the TBA is returned. `label_ingestor` also parses an address line, but a
    manual return does not need one and returning a customer address the caller
    did not ask for would put it in a response and its logs for nothing (dim 7).
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a photo of the label (jpg, png, pdf).",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if len(content) > _MAX_LABEL_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image is too large.",
        )

    try:
        from app.services.label_ingestor import LabelIngestor
        read = LabelIngestor(content).read()
    except Exception:
        # Never surface the Textract or boto exception text (dim 6).
        logger.warning(
            "manual_returns_label_scan_failed",
            extra={"company_id": str(caller.company_id)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not read that label. Type the tracking number instead.",
        )

    return LabelReadOut(
        tba=read.tba,
        confidence=read.confidence,
        lines=read.lines,
        warnings=read.warnings,
        # The address half of the read is irrelevant here, so a missing address
        # must not force manual entry of a TBA that scanned cleanly.
        needs_manual_entry=read.tba is None,
    )


# ── the three record types ────────────────────────────────────────────────────

@router.post("/rts", response_model=ManualRecordOut, status_code=status.HTTP_201_CREATED)
def record_rts(
    payload: RTSRecordIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_record),
    db: Session = Depends(get_db),
):
    """Record an undelivered package returning to station.

    D6: the type enum is unchanged from full mode — every value is an observation
    about a delivery attempt, not a fact derived from the manifest.

    `is_reattemptable` is SERVER-DERIVED from the type and never read from the
    request. A client that could set it would decide whether a package goes back
    out today, which is a rule, not an input.
    """
    route = _load_route(db, caller, payload.route_id)
    _reject_duplicate(db, RTSPackage, caller.company_id, route.id,
                      payload.tba_number, "RTS")

    walker = _executor(db, caller.company_id, route)
    explanation, _flags = scrub_note(payload.rts_explanation)

    row = RTSPackage(
        company_id=caller.company_id,
        route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        tba_number=payload.tba_number,
        rts_type=payload.rts_type,
        rts_explanation=explanation or payload.rts_type,
        is_reattemptable=is_reattemptable(payload.rts_type),
        walker_id=walker.id if walker else None,
        walker_name=(walker.name[:100] if walker else None),
        recorded_by=caller.id,
        recorded_by_name=(caller.name or "")[:100],
        source="manual",
    )
    db.add(row)
    db.flush()
    write_audit(
        db=db, company_id=str(caller.company_id), actor_id=str(caller.id),
        action_type="manual_return.rts",
        target_table="rts_packages", target_id=str(row.id),
        detail={"tba_number": payload.tba_number, "rts_type": payload.rts_type,
                "route_number": route.route_number, "source": "manual"},
    )
    db.commit()
    db.refresh(row)

    return ManualRecordOut(
        id=row.id, tba_number=row.tba_number, route_id=row.route_id,
        source=row.source, kind="rts", is_reattemptable=row.is_reattemptable,
        recorded_by_name=row.recorded_by_name,
    )


@router.post("/missing", response_model=ManualRecordOut,
             status_code=status.HTTP_201_CREATED)
def record_missing(
    payload: MissingRecordIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_record),
    db: Session = Depends(get_db),
):
    """Record a package the manifest expected but the walker never had.

    Distinct from RTS: an RTS package came back, a missing one never arrived.
    Conflating them understates delivery success and hides a station-side loss.
    """
    route = _load_route(db, caller, payload.route_id)
    _reject_duplicate(db, MissingPackage, caller.company_id, route.id,
                      payload.tba_number, "missing")

    walker = _executor(db, caller.company_id, route)
    notes, _flags = scrub_note(payload.notes)

    row = MissingPackage(
        company_id=caller.company_id,
        route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        tba_number=payload.tba_number,
        walker_id=walker.id if walker else None,
        walker_name=(walker.name[:100] if walker else None),
        recorded_by=caller.id,
        recorded_by_name=(caller.name or "")[:100],
        resolution_notes=notes,
        source="manual",
    )
    db.add(row)
    db.flush()
    write_audit(
        db=db, company_id=str(caller.company_id), actor_id=str(caller.id),
        action_type="manual_return.missing",
        target_table="missing_packages", target_id=str(row.id),
        detail={"tba_number": payload.tba_number,
                "route_number": route.route_number, "source": "manual"},
    )
    db.commit()
    db.refresh(row)

    return ManualRecordOut(
        id=row.id, tba_number=row.tba_number, route_id=row.route_id,
        source=row.source, kind="missing", recorded_by_name=row.recorded_by_name,
    )


@router.post("/damaged", response_model=ManualRecordOut,
             status_code=status.HTTP_201_CREATED)
def record_damaged(
    payload: DamagedRecordIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_record),
    db: Session = Depends(get_db),
):
    """Record a damaged package.

    `stage` separates station damage from on-route damage. Both are real and
    they have different owners — a station-damaged package never left, and
    filing it as route damage points the investigation at the wrong place.
    """
    route = _load_route(db, caller, payload.route_id)
    _reject_damaged_duplicate(db, caller.company_id, route, payload.tba_number)

    notes, _flags = scrub_note(payload.damage_notes)

    row = DamagedPackage(
        company_id=caller.company_id,
        route_date=route.route_date,
        tba_number=payload.tba_number,
        truck_assignment_id=route.truck_assignment_id,
        # No route_id: DamagedPackage is deliberately keyed by route_date +
        # truck_assignment_id, because station damage happens before a package
        # is ever on a route. Adding one here to make this endpoint symmetrical
        # would model the exception around the convenience.
        stage=payload.stage,
        damage_notes=notes or payload.stage,
        reported_by=caller.id,
        reported_by_name=(caller.name or "")[:100],
        source="manual",
    )
    db.add(row)
    db.flush()
    write_audit(
        db=db, company_id=str(caller.company_id), actor_id=str(caller.id),
        action_type="manual_return.damaged",
        target_table="damaged_packages", target_id=str(row.id),
        detail={"tba_number": payload.tba_number, "stage": payload.stage,
                "route_number": route.route_number, "source": "manual"},
    )
    db.commit()
    db.refresh(row)

    return ManualRecordOut(
        id=row.id, tba_number=row.tba_number, route_id=route.id,
        source=row.source, kind="damaged", recorded_by_name=row.reported_by_name,
    )


# ── the day's returns (D5) ────────────────────────────────────────────────────

@router.get("/{route_date}", response_model=DayReturnsOut)
def list_day_returns(
    route_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """Every manual record for a date — what dispatch reviews at end of day.

    D5 says entry is per-walker at return and submitted to dispatch at EOD. This
    is the read half of that; the existing `shift_ops` handoff remains the
    submission surface rather than a second one being invented beside it.
    """
    route_ids = [
        r[0] for r in db.query(Route.id).filter(
            Route.company_id == caller.company_id,
            Route.route_date == route_date,
        ).all()
    ]
    if not route_ids:
        return DayReturnsOut(rts=[], missing=[], damaged=[], total=0)

    rts = (
        db.query(RTSPackage)
        .filter(
            RTSPackage.company_id == caller.company_id,
            RTSPackage.route_id.in_(route_ids),
        )
        .all()
    )
    missing = (
        db.query(MissingPackage)
        .filter(
            MissingPackage.company_id == caller.company_id,
            MissingPackage.route_id.in_(route_ids),
        )
        .all()
    )
    damaged = (
        db.query(DamagedPackage)
        .filter(
            DamagedPackage.company_id == caller.company_id,
            DamagedPackage.route_date == route_date,
        )
        .all()
    )

    return DayReturnsOut(
        rts=[ManualRecordOut(id=r.id, tba_number=r.tba_number, route_id=r.route_id,
                             source=r.source, kind="rts",
                             is_reattemptable=r.is_reattemptable,
                             recorded_by_name=r.recorded_by_name) for r in rts],
        missing=[ManualRecordOut(id=m.id, tba_number=m.tba_number, route_id=m.route_id,
                                 source=m.source, kind="missing",
                                 recorded_by_name=m.recorded_by_name) for m in missing],
        # route_id is the caller-facing grouping key; DamagedPackage does not
        # carry one, so the truck assignment's first route stands in. Stated
        # rather than hidden — this is a display convenience, not a real link.
        damaged=[ManualRecordOut(id=d.id, tba_number=d.tba_number,
                                 route_id=route_ids[0],
                                 source=d.source, kind="damaged",
                                 recorded_by_name=d.reported_by_name) for d in damaged],
        total=len(rts) + len(missing) + len(damaged),
    )
