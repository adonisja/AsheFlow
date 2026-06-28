"""Sort router — manifest sort pipeline endpoints.

POST /sort/upload            — upload CSV/XLSX/PDF/image manifest, trigger async enrichment
GET  /sort/manifest/{date}/status — poll enrichment status (ready / enriching / not_found)
POST /sort/run               — run the full sort pipeline for a given date
GET  /sort/{date}            — fetch existing zone results for a date
GET  /sort/{date}/centroids  — fetch route cluster centroids for the Deck.gl density layer
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid as _uuid_mod
from datetime import date, datetime, timezone
from uuid import UUID
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.truck_zone import TruckZone
from app.models.walker_route import RouteClusterCentroid
from app.services.manifest_ingestor import FileManifestIngestor, ImageManifestIngestor, IngestResult
from app.services.run_sort import run_sort, SortError
from app.services.seed_manifest import generate_manifest
from app.services.tier1_verify import BagOverride as _BagOverride
from app.tasks.enrich_manifest import enrich_manifest_packages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sort", tags=["sort"])

allow_sort  = RoleChecker(["dispatch", "management", "admin"])
allow_admin = RoleChecker(["admin"])

_REDIS_TTL_SECONDS = 86_400   # matches enrich_manifest task
_ENRICHING_KEY_TTL = 300      # 5-min sentinel while Celery task is in flight
_MAX_UPLOAD_BYTES  = 10 * 1024 * 1024   # 10 MB — daily manifest should be well under 1 MB


# ── request / response schemas ────────────────────────────────────────────────

class BagOverrideIn(BaseModel):
    """Dispatch-confirmed truck assignment for a bag that failed tier-1."""
    bag_id: str
    truck_id: UUID


class SortRunRequest(BaseModel):
    sort_date: date
    force: bool = False
    overrides: list[BagOverrideIn] = []     # empty on first run; populated on resubmit


class BagResultOut(BaseModel):
    bag_id: str
    inferred_truck_id: Optional[UUID] = None
    classification: str                     # "clean" | "stray" | "uncertain" | "misaligned"
    total_packages: int
    outside_packages: int
    outside_pct: float
    outside_tbas: list[str]
    outlier_tbas: list[str]
    suggested_truck_id: Optional[UUID] = None
    unresolvable: bool


class ClusterAssignmentOut(BaseModel):
    truck_id: UUID
    truck_name: str
    match_type: str
    workload_score: Optional[float] = None
    is_overflow: bool
    package_count: int


class SortRunResponse(BaseModel):
    sort_date: date
    package_count: int
    outlier_count: int
    cluster_count: int
    tier1_passed: bool
    was_forced: bool
    zones_created: int
    assignments: list[ClusterAssignmentOut]
    flagged_bags: list[BagResultOut]        # empty when tier1_passed=True or was_forced=True


class ZoneOut(BaseModel):
    id: UUID
    truck_id: UUID
    zone_label: str
    truck_polygon: list[dict]
    zone_date: date
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SortStatusResponse(BaseModel):
    sort_date: date
    zones: list[ZoneOut]
    zone_count: int


class ManifestUploadResponse(BaseModel):
    sort_date: date
    package_count: int
    pending_count: int          # rows with missing/unreadable TBA — need dispatch resolution
    warnings: list[str]         # count-reconciliation warnings (mismatches vs manifest header)
    status: str                 # "enriching"


class ManifestStatusResponse(BaseModel):
    sort_date: date
    status: str                          # "ready" | "enriching" | "failed" | "not_found"
    package_count: int                   # 0 when not_found, enriching, or failed
    failed_count: int                    # packages that could not be enriched (block_key=None)
    failed_reason: str | None = None     # human-readable failure cause when status="failed"
    packages_processed: int | None = None  # live count during enriching
    packages_total: int | None = None      # total submitted to enrichment task


# ── Borough inference ─────────────────────────────────────────────────────────
# Approximate bounding boxes for NYC boroughs (lat_min, lat_max, lng_min, lng_max).
# Used only when admin has not configured geoclient_borough on CompanyConfig.
# Non-NYC deployments will fall back to "manhattan" which callers can override
# by setting CompanyConfig.geoclient_borough explicitly.
_BOROUGH_BOXES = [
    ("manhattan", 40.700, 40.882, -74.020, -73.907),
    ("brooklyn",  40.551, 40.740, -74.042, -73.833),
    ("queens",    40.541, 40.800, -73.962, -73.700),
    ("bronx",     40.785, 40.917, -73.933, -73.765),
    ("staten island", 40.477, 40.651, -74.259, -74.034),
]


def _infer_borough(packages: list) -> str | None:
    """Return the NYC borough name that contains the median package coordinates.

    Uses RawPackage objects (have .lat/.lng attributes).
    Returns None if coordinates don't fall within any known borough box.
    """
    if not packages:
        return None
    lats = sorted(p.lat for p in packages if p.lat)
    lngs = sorted(p.lng for p in packages if p.lng)
    if not lats or not lngs:
        return None
    median_lat = lats[len(lats) // 2]
    median_lng = lngs[len(lngs) // 2]
    for name, lat_min, lat_max, lng_min, lng_max in _BOROUGH_BOXES:
        if lat_min <= median_lat <= lat_max and lng_min <= median_lng <= lng_max:
            return name
    return None


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _manifest_key(company_id: str, sort_date: str) -> str:
    return f"manifest:{company_id}:{sort_date}"


def _enriching_key(company_id: str, sort_date: str) -> str:
    return f"manifest_enriching:{company_id}:{sort_date}"


# ── endpoints ─────────────────────────────────────────────────────────────────

_SORT_ERROR_STATUS = {
    "no_manifest":    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "no_trucks":      status.HTTP_422_UNPROCESSABLE_CONTENT,
    "no_packages":    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "tier1_failed":   status.HTTP_409_CONFLICT,
    "config_missing": status.HTTP_503_SERVICE_UNAVAILABLE,
}


@router.post("/upload", response_model=ManifestUploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_manifest(
    sort_date: date = Form(...),
    file: UploadFile = File(...),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Upload a manifest file and trigger async address enrichment.

    Accepts CSV, XLSX, XLS (tabular) or PDF, JPG, PNG (Textract OCR path).
    The file is parsed immediately (synchronous) to validate it and get a
    package count.  Address enrichment (GeoClient calls + block_key derivation)
    runs asynchronously via Celery.  Poll GET /sort/manifest/{date}/status to
    know when sort is runnable.

    The sort_date form field must match the date the manifest covers — it is
    used as the Redis cache key so run_sort() can find the enriched packages.
    """
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    _IMAGE_EXTS = {"pdf", "jpg", "jpeg", "png"}
    _SHEET_EXTS = {"csv", "xlsx", "xls"}
    if ext not in _SHEET_EXTS | _IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported file type. Upload a CSV, XLSX, PDF, JPG, or PNG file.",
        )

    # Enforce size limit before writing to disk
    contents = file.file.read(_MAX_UPLOAD_BYTES + 1)
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    if ext in _IMAGE_EXTS:
        try:
            result: IngestResult = ImageManifestIngestor(contents).ingest()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image parsing (Textract) is not available in this environment.",
            ) from exc
    else:
        # Write to a temp file so FileManifestIngestor can read it by path
        suffix = f".{ext}"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(contents)
            tmp.flush()
            tmp.close()
            result = FileManifestIngestor(tmp.name).ingest()
        finally:
            os.unlink(tmp.name)

    if not result.packages and not result.pending:
        logger.warning(
            "manifest_ingest_empty",
            extra={
                "company_id": str(caller.company_id),
                "sort_date":  sort_date.isoformat(),
                "filename":   file.filename,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No packages could be parsed from the file. Check column headers.",
        )

    # Resolve borough for GeoClient enrichment.
    # Priority: 1) admin-configured value on CompanyConfig
    #           2) inferred from median package latitude/longitude
    #           3) platform default "manhattan"
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
    if cfg and cfg.geoclient_borough:
        borough = cfg.geoclient_borough
    else:
        borough = _infer_borough(result.packages) or "manhattan"

    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()

    # Set enriching sentinel so status endpoint returns "enriching" immediately.
    # Also pre-write a worker_unreachable failure key (TTL 24h) that the task
    # clears on first receipt. If Celery discards the task (unregistered, worker
    # down, etc.) the key persists and the status endpoint returns "failed" with
    # an actionable message instead of silently reverting to "not_found".
    r = _redis()
    r.setex(_enriching_key(cid_str, date_str), _ENRICHING_KEY_TTL, "1")
    r.setex(f"manifest_failed:{cid_str}:{date_str}", _REDIS_TTL_SECONDS, "worker_unreachable")

    # Only valid packages (with TBAs) go to the enrichment task.
    # Pending packages have no TBA — dispatch must resolve them via a separate input.
    raw_dicts = [
        {
            "tba":          p.tba,
            "lat":          p.lat,
            "lng":          p.lng,
            "address":      p.address,
            "bag_id":       p.bag_id,
            "tag_number":   p.tag_number,
            "package_type": p.package_type,
        }
        for p in result.packages
    ]
    enrich_manifest_packages.delay(
        company_id=cid_str,
        sort_date=date_str,
        packages=raw_dicts,
        borough=borough,
    )

    logger.info(
        "manifest upload accepted",
        extra={
            "company_id":    cid_str,
            "sort_date":     date_str,
            "packages":      len(result.packages),
            "pending":       len(result.pending),
            "warnings":      len(result.warnings),
        },
    )

    return ManifestUploadResponse(
        sort_date=sort_date,
        package_count=len(result.packages),
        pending_count=len(result.pending),
        warnings=result.warnings,
        status="enriching",
    )


@router.get("/manifest/{sort_date}/status", response_model=ManifestStatusResponse)
def get_manifest_status(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
):
    """Poll whether the manifest for a given date is ready to sort.

    Returns:
      "enriching"  — upload accepted, Celery task still running
      "ready"      — enriched packages are cached in Redis; sort is runnable
      "not_found"  — no manifest uploaded for this date (or cache expired)
    """
    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()

    enriching = r.exists(_enriching_key(cid_str, date_str))
    failed_reason = r.get(f"manifest_failed:{cid_str}:{date_str}")
    raw = r.get(_manifest_key(cid_str, date_str))
    progress_raw = r.get(f"manifest_progress:{cid_str}:{date_str}")

    if raw is not None:
        try:
            packages = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "manifest_cache_corrupt",
                extra={"company_id": cid_str, "sort_date": date_str, "error": str(exc)[:200]},
            )
            return ManifestStatusResponse(
                sort_date=sort_date,
                status="failed",
                package_count=0,
                failed_count=0,
                failed_reason="Manifest data in cache is corrupted — re-upload the file.",
            )
        failed_count = sum(1 for p in packages if p.get("block_key") is None)
        logger.info(
            "manifest_status_ready",
            extra={
                "company_id":   cid_str,
                "sort_date":    date_str,
                "package_count": len(packages),
                "failed_count": failed_count,
            },
        )
        return ManifestStatusResponse(
            sort_date=sort_date,
            status="ready",
            package_count=len(packages),
            failed_count=failed_count,
        )

    # Check failed before enriching: the task deletes the enriching sentinel on
    # completion (success or threshold failure), but a real failure reason is the
    # authoritative signal — surface it immediately regardless of sentinel state.
    if failed_reason and failed_reason != "worker_unreachable":
        if "no_api_key" in failed_reason:
            human_reason = "GeoClient API key is not configured on the server — contact your admin."
        elif "enrichment_threshold_exceeded" in failed_reason:
            human_reason = "Too many packages could not be geocoded — fix the issue and re-upload."
        else:
            human_reason = "Enrichment failed unexpectedly — re-upload the manifest or contact your admin."
        return ManifestStatusResponse(
            sort_date=sort_date,
            status="failed",
            package_count=0,
            failed_count=0,
            failed_reason=human_reason,
        )

    if enriching:
        packages_processed = None
        packages_total = None
        if progress_raw:
            try:
                prog = json.loads(progress_raw)
                packages_processed = prog.get("processed")
                packages_total = prog.get("total")
            except (json.JSONDecodeError, AttributeError):
                pass
        return ManifestStatusResponse(
            sort_date=sort_date,
            status="enriching",
            package_count=0,
            failed_count=0,
            packages_processed=packages_processed,
            packages_total=packages_total,
        )

    if failed_reason:  # worker_unreachable — enriching sentinel already expired
        return ManifestStatusResponse(
            sort_date=sort_date,
            status="failed",
            package_count=0,
            failed_count=0,
            failed_reason="Enrichment task was not received by the worker — Celery may be down or the task is not registered. Contact your admin.",
        )

    return ManifestStatusResponse(
        sort_date=sort_date,
        status="not_found",
        package_count=0,
        failed_count=0,
    )


@router.post("/run", response_model=SortRunResponse, status_code=status.HTTP_200_OK)
def run_sort_endpoint(
    body: SortRunRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Run the manifest sort pipeline for the given date.

    - Loads enriched packages from Redis (must have been enriched first via /sort/upload)
    - Clusters packages with DBSCAN → assigns clusters to trucks
    - Derives bag-to-truck mapping from the manifest (bag_id per package)
    - Tier-1 verification: flags bags whose TBAs don't match their inferred truck
    - If tier-1 passes (or force=True), writes TruckZone rows and commits
    - Returns the full assignment breakdown and any flagged bags

    409 Conflict when tier-1 flags bags and force=False — display flagged bags
    with suggested trucks, let dispatch confirm or override, then resubmit
    with force=True and the confirmed overrides.
    """
    # Validate override truck IDs belong to this company's active trucks
    if body.overrides:
        company_truck_ids = {
            t.id for t in db.query(Truck).filter(
                Truck.company_id == caller.company_id,
                Truck.is_active.is_(True),
            ).all()
        }
        invalid_trucks = [
            str(ov.truck_id) for ov in body.overrides
            if ov.truck_id not in company_truck_ids
        ]
        if invalid_trucks:
            raise HTTPException(
                status_code=400,
                detail=f"Override references unknown or inactive truck IDs: {', '.join(invalid_trucks)}",
            )

    bag_overrides = [
        _BagOverride(bag_id=ov.bag_id, truck_id=ov.truck_id)
        for ov in body.overrides
    ]

    try:
        result = run_sort(
            company_id      = caller.company_id,
            sort_date       = body.sort_date,
            overrides       = bag_overrides,
            created_by      = caller.id,
            created_by_name = caller.name,
            db              = db,
            force           = body.force,
        )
    except SortError as exc:
        http_status = _SORT_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=http_status, detail=exc.detail)

    # Stamp sort actor + timestamp on every TruckAssignment for this company + date.
    # Only runs when zones were actually persisted (tier1 passed or force=True).
    if result.zones_persisted:
        db.query(TruckAssignment).filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == body.sort_date,
        ).update(
            {
                "sort_initiated_by": caller.id,
                "sort_committed_at": datetime.now(timezone.utc),
            },
            synchronize_session="fetch",
        )

    # Write RouteClusterCentroid rows — one per assigned cluster, for the Deck.gl density layer.
    # Delete stale rows for this date first (idempotent re-sort).
    if result.zones_persisted:
        db.query(RouteClusterCentroid).filter(
            RouteClusterCentroid.company_id == caller.company_id,
            RouteClusterCentroid.route_date == body.sort_date,
        ).delete(synchronize_session="fetch")

        # Resolve truck_assignment_id for each truck in the proposal
        ta_by_truck: dict = {
            ta.truck_id: ta.id
            for ta in db.query(TruckAssignment).filter(
                TruckAssignment.company_id == caller.company_id,
                TruckAssignment.date == body.sort_date,
            ).all()
        }

        for assignment in result.proposal.assignments:
            c = assignment.cluster
            db.add(RouteClusterCentroid(
                company_id          = caller.company_id,
                truck_assignment_id = ta_by_truck.get(assignment.truck_id),
                route_date          = body.sort_date,
                centroid_lat        = c.centroid["lat"],
                centroid_lng        = c.centroid["lng"],
                package_count       = len(c.packages),
                truck_zone_label    = assignment.truck_name,
            ))

    # Audit log when dispatch overrides a tier-1 failure
    if result.was_forced:
        db.add(AuditLog(
            company_id      = caller.company_id,
            actor_id        = caller.id,
            action_type     = "sort.tier1_force_override",
            target_table    = "truck_zones",
            target_id       = _uuid_mod.uuid4(),   # synthetic — no single row; use new UUID as event ID
            after_snapshot  = {
                "sort_date":    body.sort_date.isoformat(),
                "flagged_totes": len(result.verification.flagged),
                "zones_created": len(result.zones_persisted),
            },
        ))

    db.commit()

    assignments_out = [
        ClusterAssignmentOut(
            truck_id       = a.truck_id,
            truck_name     = a.truck_name,
            match_type     = a.match_type,
            workload_score = a.workload_score,
            is_overflow    = a.is_overflow,
            package_count  = len(a.cluster.packages),
        )
        for a in result.proposal.assignments
    ]

    flagged_out = [
        BagResultOut(
            bag_id             = b.bag_id,
            inferred_truck_id  = b.inferred_truck_id,
            classification     = b.classification,
            total_packages     = b.total_packages,
            outside_packages   = b.outside_packages,
            outside_pct        = b.outside_pct,
            outside_tbas       = b.outside_tbas,
            outlier_tbas       = b.outlier_tbas,
            suggested_truck_id = b.suggested_truck_id,
            unresolvable       = b.unresolvable,
        )
        for b in result.verification.flagged
    ]

    return SortRunResponse(
        sort_date     = result.sort_date,
        package_count = result.package_count,
        outlier_count = result.outlier_count,
        cluster_count = result.cluster_count,
        tier1_passed  = result.tier1_passed,
        was_forced    = result.was_forced,
        zones_created = len(result.zones_persisted),
        assignments   = assignments_out,
        flagged_bags  = flagged_out,
    )


class CentroidOut(BaseModel):
    centroid_lat: float
    centroid_lng: float
    package_count: int
    truck_zone_label: str | None
    model_config = ConfigDict(from_attributes=True)


class CentroidsResponse(BaseModel):
    sort_date: date
    centroids: list[CentroidOut]


@router.get("/{sort_date}/centroids", response_model=CentroidsResponse)
def get_sort_centroids(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Route cluster centroids for the Deck.gl density layer."""
    centroids = (
        db.query(RouteClusterCentroid)
        .filter(
            RouteClusterCentroid.company_id == caller.company_id,
            RouteClusterCentroid.route_date == sort_date,
        )
        .all()
    )
    return CentroidsResponse(sort_date=sort_date, centroids=centroids)


@router.get("/{sort_date}", response_model=SortStatusResponse)
def get_sort_status(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Return the active zones persisted for a given sort date."""
    zones = (
        db.query(TruckZone)
        .filter(
            TruckZone.company_id == caller.company_id,
            TruckZone.zone_date == sort_date,
            TruckZone.is_active.is_(True),
        )
        .order_by(TruckZone.zone_label)
        .all()
    )
    return SortStatusResponse(
        sort_date  = sort_date,
        zones      = zones,
        zone_count = len(zones),
    )


# ── Tote / TBA reassignment ───────────────────────────────────────────────────

class TbaReassignRequest(BaseModel):
    """Move a set of TBA numbers from one TruckZone to another.

    Used when dispatch physically moves a tote (or individual packages) from
    one truck to another after the sort has already been committed.  The caller
    supplies the TBA numbers to move — not the tote_id, which is not persisted
    in TruckZone — and the destination zone id.
    """
    tba_numbers:         list[str]
    destination_zone_id: UUID


class TbaReassignResponse(BaseModel):
    source_zone_id:      UUID
    destination_zone_id: UUID
    moved_tbas:          list[str]
    source_remaining:    int
    destination_total:   int


@router.post(
    "/zones/{zone_id}/reassign-tbas",
    response_model=TbaReassignResponse,
    status_code=status.HTTP_200_OK,
)
def reassign_tbas(
    zone_id: UUID,
    body: TbaReassignRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Move TBA numbers from one TruckZone to another after sort has run.

    Dispatch uses this when a tote is physically moved between trucks at the
    anchor point — e.g. an overflow bag was placed on the wrong truck.
    Both zones must belong to the same company and be active.
    Only TBAs actually present in the source zone are moved; any unknown TBAs
    in the request are silently ignored.
    """
    if not body.tba_numbers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="tba_numbers must not be empty.",
        )

    source = (
        db.query(TruckZone)
        .filter(
            TruckZone.id == zone_id,
            TruckZone.company_id == caller.company_id,
            TruckZone.is_active.is_(True),
        )
        .first()
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source zone not found.")

    destination = (
        db.query(TruckZone)
        .filter(
            TruckZone.id == body.destination_zone_id,
            TruckZone.company_id == caller.company_id,
            TruckZone.is_active.is_(True),
        )
        .first()
    )
    if not destination:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Destination zone not found.")
    if source.id == destination.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Source and destination zones must be different.",
        )

    source_zone_tbas: list[str] = list(source.package_tbas or [])
    dest_zone_tbas:   list[str] = list(destination.package_tbas or [])
    requested_tbas = set(body.tba_numbers)
    tbas_to_move = [tba for tba in source_zone_tbas if tba in requested_tbas]

    if not tbas_to_move:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="None of the supplied TBA numbers are present in the source zone.",
        )

    tbas_to_move_set = set(tbas_to_move)
    updated_source_tbas = [tba for tba in source_zone_tbas if tba not in tbas_to_move_set]
    updated_dest_tbas   = dest_zone_tbas + tbas_to_move

    source.package_tbas      = updated_source_tbas
    destination.package_tbas = updated_dest_tbas

    db.add(AuditLog(
        company_id    = caller.company_id,
        actor_id      = caller.id,
        action_type   = "sort.tba_reassign",
        target_table  = "truck_zones",
        target_id     = source.id,
        after_snapshot = {
            "source_zone_id":      str(source.id),
            "destination_zone_id": str(destination.id),
            "moved_tbas":          tbas_to_move,
        },
    ))
    db.commit()

    logger.info(
        "tba_reassign",
        extra={
            "company_id":          str(caller.company_id),
            "source_zone_id":      str(source.id),
            "destination_zone_id": str(destination.id),
            "moved_count":         len(tbas_to_move),
        },
    )

    return TbaReassignResponse(
        source_zone_id      = source.id,
        destination_zone_id = destination.id,
        moved_tbas          = tbas_to_move,
        source_remaining    = len(updated_source_tbas),
        destination_total   = len(updated_dest_tbas),
    )


# ── Seed manifest (admin-only dev tool) ───────────────────────────────────────

class SeedManifestPackagePreview(BaseModel):
    tracking_id:  str
    address:      str
    bag_id:       str
    package_type: str
    latitude:     float
    longitude:    float


class SeedManifestResponse(BaseModel):
    sort_date:         date
    package_count:     int
    tote_count:        int
    ov_count:          int
    out_of_zone_count: int
    misrouted_count:   int
    truck_count:       int
    truck_names:       list[str]
    preview_rows:      list[SeedManifestPackagePreview]
    csv_b64:           str


@router.post(
    "/seed-manifest",
    response_model=SeedManifestResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a synthetic test manifest (admin only)",
)
def seed_manifest(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Generate a synthetic manifest (10 000–13 000 packages) for end-to-end pipeline testing.

    Only callable by admin role.  Requires that truck dispatch has already run for
    the requested date (at least one TruckAssignment must exist) so the caller
    knows which trucks they are testing against.

    Returns:
    - Summary counts (packages, totes, OVs, trucks)
    - First 20 rows as a preview table
    - Base-64-encoded CSV bytes — pass directly to POST /sort/upload to start enrichment
    """
    import base64

    assignment_rows = (
        db.query(TruckAssignment)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == sort_date,
        )
        .all()
    )
    if not assignment_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"No truck assignments found for {sort_date}. "
                "Run dispatch for this date first, then generate the test manifest."
            ),
        )

    truck_ids = [a.truck_id for a in assignment_rows]
    trucks = db.query(Truck).filter(
        Truck.id.in_(truck_ids),
        Truck.company_id == caller.company_id,
    ).all()
    truck_names = sorted(t.name for t in trucks)

    result = generate_manifest()

    preview = [
        SeedManifestPackagePreview(
            tracking_id  = r["Tracking ID"],
            address      = r["Address"],
            bag_id       = r["Bag ID"],
            package_type = r["Package Type"] or "—",
            latitude     = r["Latitude"],
            longitude    = r["Longitude"],
        )
        for r in result.rows[:20]
    ]

    return SeedManifestResponse(
        sort_date         = sort_date,
        package_count     = result.package_count,
        tote_count        = result.tote_count,
        ov_count          = result.ov_count,
        out_of_zone_count = result.out_of_zone_count,
        misrouted_count   = result.misrouted_count,
        truck_count       = len(assignment_rows),
        truck_names       = truck_names,
        preview_rows      = preview,
        csv_b64           = base64.b64encode(result.csv_bytes).decode("ascii"),
    )
