"""BTR sheet ingestion — preview, then confirm (ADR-290).

TWO STEPS, DELIBERATELY.

    POST /btr-sheets/preview   parse a file, return what was read. WRITES NOTHING.
    POST /btr-sheets/confirm   persist a reviewed sheet.

An OCR read is a suggestion, not a fact (ADR-290 D3). The sample sheet is
creased and its Bag Labels column wraps mid-cell, and a misread bag id silently
mis-assigns a whole tote. So the image path must pass through a human, and the
cleanest way to guarantee that is to give parsing no write capability at all.

CSV and manual reads are exact and could technically write in one step. They
still go through confirm — one flow is easier to reason about than two, and the
operator reviewing a CSV costs seconds while a divergent second path costs a
class of bug.

MODE-INDEPENDENT (ADR-290 D1). Registered WITHOUT RequireMode: in workforce mode
this is the bag inventory the sort consumes, and in full mode it is a dock-time
reconciliation source. Gating it would remove the reconciliation benefit from
exactly the tenants who have a manifest to reconcile against.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.btr_sheet import BTRSheet, BTRRoute, BTRBag, BTROVZone
from app.models.company import Company
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.services.audit import write_audit
from app.core.bag_colors import canonical_hex
from app.services.btr_ingestor import (
    BTRSheetRead, CSVBTRIngestor, ImageBTRIngestor, ManualBTRIngestor, reconcile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/btr-sheets", tags=["btr-sheets"])

# Dispatch imports the CSV; a captain photographs the sheet at the truck. Both
# initiate operationally, which is what the gate reflects (dim 2) — not merely
# who has authority.
_allow_ingest = RoleChecker(["captain", "driver", "dispatch", "management", "admin"])
_allow_read = RoleChecker(
    ["captain", "driver", "trainer", "dispatch", "management", "admin"]
)

_CSV_EXTS = {"csv"}
_IMAGE_EXTS = {"pdf", "jpg", "jpeg", "png"}

# A BTR sheet is one page. 10 MB is generous for a phone photo and small enough
# that a mis-selected video is rejected before Textract is billed for it.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# ── request schemas (dim 9: concrete types, bounds, extra=forbid) ─────────────

class BagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bag_id: str = Field(..., min_length=1, max_length=50)
    # Resolved hex from the label's colour word. Null renders a neutral pill.
    bag_color: Optional[str] = Field(None, max_length=10)


class OVZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_label: str = Field(..., min_length=1, max_length=30)
    ov_count: int = Field(..., ge=0, le=999)


class RouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amazon_route_name: str = Field(..., min_length=1, max_length=30)
    # Optional, not defaulted to 0: an unread cell is unknown, and reporting it
    # as zero would make the full-mode reconciliation announce a discrepancy
    # that is really a camera miss.
    package_count: Optional[int] = Field(None, ge=0, le=99_999)
    bag_count: Optional[int] = Field(None, ge=0, le=999)
    ov_count: Optional[int] = Field(None, ge=0, le=999)
    bags: list[BagIn] = Field(default_factory=list, max_length=200)
    ov_zones: list[OVZoneIn] = Field(default_factory=list, max_length=50)


class BTRSheetConfirm(BaseModel):
    """A sheet a human has reviewed, ready to persist."""
    model_config = ConfigDict(extra="forbid")

    truck_id: UUID
    sheet_date: date
    source: Literal["csv", "image", "manual"]

    btr_loading_zone: Optional[str] = Field(None, max_length=50)
    service_type: Optional[str] = Field(None, max_length=60)
    dsp: Optional[str] = Field(None, max_length=100)
    amazon_route_count: Optional[int] = Field(None, ge=0, le=999)
    amazon_anchor_lat: Optional[float] = Field(None, ge=-90, le=90)
    amazon_anchor_lng: Optional[float] = Field(None, ge=-180, le=180)

    # A truck carries a bounded number of Amazon routes; the real sheet shows 12.
    routes: list[RouteIn] = Field(default_factory=list, max_length=100)


# ── response schemas ──────────────────────────────────────────────────────────

class BagOut(BaseModel):
    bag_id: str
    bag_color: Optional[str] = None
    amazon_route_name: Optional[str] = None


class OVZoneOut(BaseModel):
    zone_label: str
    ov_count: int


class RouteOut(BaseModel):
    amazon_route_name: str
    package_count: Optional[int] = None
    bag_count: Optional[int] = None
    ov_count: Optional[int] = None
    bags: list[BagOut] = []
    ov_zones: list[OVZoneOut] = []


class BTRSheetOut(BaseModel):
    btr_loading_zone: Optional[str] = None
    service_type: Optional[str] = None
    dsp: Optional[str] = None
    amazon_route_count: Optional[int] = None
    amazon_anchor_lat: Optional[float] = None
    amazon_anchor_lng: Optional[float] = None
    routes: list[RouteOut] = []
    # Non-blocking: OV zones not summing to OV Count, bag labels not matching
    # Bag Count. Surfaced so the reviewer can check that cell by eye.
    warnings: list[str] = []
    # 0.0–1.0 for the image path; null for CSV and manual, which are exact.
    confidence: Optional[float] = None
    # Set on preview when the sheet's DSP does not match this company's
    # configured name. The reviewer must resolve it before confirm will accept.
    dsp_mismatch: Optional[str] = None
    total_bags: int = 0


class BTRSheetSaved(BaseModel):
    id: UUID
    truck_id: UUID
    sheet_date: date
    btr_loading_zone: Optional[str] = None
    route_count: int
    bag_count: int
    source: str


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_out(sheet: BTRSheetRead, dsp_mismatch: Optional[str] = None) -> BTRSheetOut:
    return BTRSheetOut(
        btr_loading_zone=sheet.btr_loading_zone,
        service_type=sheet.service_type,
        dsp=sheet.dsp,
        amazon_route_count=sheet.amazon_route_count,
        amazon_anchor_lat=sheet.amazon_anchor_lat,
        amazon_anchor_lng=sheet.amazon_anchor_lng,
        routes=[
            RouteOut(
                amazon_route_name=r.amazon_route_name,
                package_count=r.package_count,
                bag_count=r.bag_count,
                ov_count=r.ov_count,
                bags=[BagOut(bag_id=b.bag_id, bag_color=canonical_hex(b.bag_color),
                             amazon_route_name=r.amazon_route_name) for b in r.bags],
                ov_zones=[OVZoneOut(zone_label=z.zone_label, ov_count=z.ov_count)
                          for z in r.ov_zones],
            )
            for r in sheet.routes
        ],
        warnings=sheet.warnings,
        confidence=sheet.confidence,
        dsp_mismatch=dsp_mismatch,
        total_bags=sheet.bag_count,
    )


def _check_dsp(db: Session, company_id: UUID, sheet_dsp: Optional[str]) -> Optional[str]:
    """ADR-290 D6. Returns a human-readable mismatch, or None when it is fine.

    A mismatch means the wrong sheet was photographed — another DSP's truck at
    the same station. Importing it would attribute someone else's totes to this
    company, so confirm refuses outright rather than importing partially.

    "Not configured" is NOT a match. With no `amazon_dsp_name` set we cannot
    validate, and inventing a pass would defeat the check for exactly the
    companies that never set it up.
    """
    if not sheet_dsp:
        return None      # the sheet did not carry a DSP cell — nothing to check

    company = db.query(Company).filter(Company.id == company_id).first()
    configured = (company.amazon_dsp_name or "").strip() if company else ""
    if not configured:
        return (
            f"This sheet is for DSP '{sheet_dsp}', but no Amazon DSP name is "
            f"configured for your company. Set it in company settings first."
        )
    if configured.upper() != sheet_dsp.strip().upper():
        return (
            f"This sheet is for DSP '{sheet_dsp}', but your company is "
            f"'{configured}'. This looks like another DSP's sheet."
        )
    return None


def _load_truck(db: Session, company_id: UUID, truck_id: UUID) -> Truck:
    truck = (
        db.query(Truck)
        .filter(Truck.id == truck_id, Truck.company_id == company_id)
        .first()
    )
    if truck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found.")
    return truck


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/preview", response_model=BTRSheetOut)
async def preview_btr_sheet(
    file: UploadFile = File(...),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_ingest),
    db: Session = Depends(get_db),
):
    """Parse a BTR sheet and return what was read. **Writes nothing.**

    CSV is exact. An image goes through Textract and carries a confidence score
    so the client can flag a shaky read — ADR-290 D3 requires a human to confirm
    either way, and giving this endpoint no write path is what enforces it.
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _CSV_EXTS | _IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a CSV export or a photo of the sheet (pdf, jpg, png).",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large. A BTR sheet is one page.",
        )

    try:
        if ext in _CSV_EXTS:
            sheet = CSVBTRIngestor(content).ingest()
        else:
            sheet = ImageBTRIngestor(content).ingest()
    except Exception:
        # Never surface the parser or Textract exception text (dim 6) — it can
        # carry file paths and AWS detail. The log keeps the type for debugging.
        logger.warning(
            "btr_preview_parse_failed",
            extra={"company_id": str(caller.company_id), "ext": ext},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not read that sheet. Check it is a BTR sheet, or enter it manually.",
        )

    if not sheet.routes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No routes found on that sheet. Check the photo includes the Pick List.",
        )

    return _to_out(sheet, _check_dsp(db, caller.company_id, sheet.dsp))


@router.post("/confirm", response_model=BTRSheetSaved,
             status_code=status.HTTP_201_CREATED)
def confirm_btr_sheet(
    payload: BTRSheetConfirm,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_ingest),
    db: Session = Depends(get_db),
):
    """Persist a reviewed BTR sheet.

    Re-importing the same truck-day REPLACES the previous sheet: a second photo
    is a correction, not a second truck. Children cascade on delete, so the
    replacement cannot leave orphaned bags behind.
    """
    _load_truck(db, caller.company_id, payload.truck_id)

    # D6: refuse outright. A partial import of another DSP's sheet would
    # attribute their totes to this company.
    mismatch = _check_dsp(db, caller.company_id, payload.dsp)
    if mismatch:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=mismatch)

    existing = (
        db.query(BTRSheet)
        .filter(
            BTRSheet.company_id == caller.company_id,
            BTRSheet.truck_id == payload.truck_id,
            BTRSheet.sheet_date == payload.sheet_date,
        )
        .first()
    )
    replaced = existing is not None
    if existing is not None:
        db.delete(existing)
        db.flush()          # release the unique constraint before re-inserting

    sheet = BTRSheet(
        company_id=caller.company_id,
        truck_id=payload.truck_id,
        sheet_date=payload.sheet_date,
        btr_loading_zone=payload.btr_loading_zone,
        service_type=payload.service_type,
        amazon_route_count=payload.amazon_route_count,
        amazon_anchor_lat=payload.amazon_anchor_lat,
        amazon_anchor_lng=payload.amazon_anchor_lng,
        source=payload.source,
        ingested_by=caller.id,
    )
    db.add(sheet)
    db.flush()

    bag_total = 0
    for r in payload.routes:
        route = BTRRoute(
            company_id=caller.company_id,
            btr_sheet_id=sheet.id,
            amazon_route_name=r.amazon_route_name,
            package_count=r.package_count,
            bag_count=r.bag_count,
            ov_count=r.ov_count,
        )
        db.add(route)
        db.flush()

        seen: set[str] = set()
        for b in r.bags:
            # A tote is unique per SHEET. The same id appearing under two routes
            # is a misread, and inserting both would violate the constraint and
            # 500 the request — skip the duplicate and let reconciliation's bag
            # count warning surface it instead.
            if b.bag_id in seen:
                continue
            seen.add(b.bag_id)
            db.add(BTRBag(
                company_id=caller.company_id,
                btr_sheet_id=sheet.id,
                btr_route_id=route.id,
                bag_id=b.bag_id,
                bag_color=canonical_hex(b.bag_color),
                amazon_route_name=r.amazon_route_name,
            ))
            bag_total += 1

        zones_seen: set[str] = set()
        for z in r.ov_zones:
            if z.zone_label in zones_seen:
                continue
            zones_seen.add(z.zone_label)
            db.add(BTROVZone(
                company_id=caller.company_id,
                btr_route_id=route.id,
                zone_label=z.zone_label,
                ov_count=z.ov_count,
            ))

    # D4: denormalise the loading zone onto today's assignment so the dispatch
    # board and the driver's card can show it without joining the sheet tables.
    # dock_zone is a DIFFERENT field (where the driver collects the truck) and is
    # deliberately not touched.
    if payload.btr_loading_zone:
        assignment = (
            db.query(TruckAssignment)
            .filter(
                TruckAssignment.company_id == caller.company_id,
                TruckAssignment.truck_id == payload.truck_id,
                TruckAssignment.date == payload.sheet_date,
            )
            .first()
        )
        if assignment is not None:
            assignment.btr_loading_zone = payload.btr_loading_zone[:50]

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="btr_sheet.import",
        target_table="btr_sheets",
        target_id=str(sheet.id),
        detail={
            "truck_id": str(payload.truck_id),
            "sheet_date": payload.sheet_date.isoformat(),
            "source": payload.source,
            "routes": len(payload.routes),
            "bags": bag_total,
            "replaced_previous": replaced,
            "btr_loading_zone": payload.btr_loading_zone,
        },
    )
    db.commit()
    db.refresh(sheet)

    return BTRSheetSaved(
        id=sheet.id,
        truck_id=sheet.truck_id,
        sheet_date=sheet.sheet_date,
        btr_loading_zone=sheet.btr_loading_zone,
        route_count=len(payload.routes),
        bag_count=bag_total,
        source=sheet.source,
    )


@router.get("/{sheet_date}", response_model=list[BTRSheetSaved])
def list_btr_sheets(
    sheet_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """Every BTR sheet imported for a date, across this company's trucks."""
    sheets = (
        db.query(BTRSheet)
        .filter(
            BTRSheet.company_id == caller.company_id,
            BTRSheet.sheet_date == sheet_date,
        )
        .order_by(BTRSheet.btr_loading_zone.asc())
        .all()
    )
    out: list[BTRSheetSaved] = []
    for s in sheets:
        routes = (
            db.query(BTRRoute)
            .filter(
                BTRRoute.company_id == caller.company_id,
                BTRRoute.btr_sheet_id == s.id,
            )
            .count()
        )
        bags = (
            db.query(BTRBag)
            .filter(
                BTRBag.company_id == caller.company_id,
                BTRBag.btr_sheet_id == s.id,
            )
            .count()
        )
        out.append(BTRSheetSaved(
            id=s.id, truck_id=s.truck_id, sheet_date=s.sheet_date,
            btr_loading_zone=s.btr_loading_zone,
            route_count=routes, bag_count=bags, source=s.source,
        ))
    return out
