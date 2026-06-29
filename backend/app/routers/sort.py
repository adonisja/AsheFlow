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
from datetime import date
from uuid import UUID
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.truck_zone import TruckZone
from app.models.walker_route import RouteClusterCentroid
from app.services.manifest_ingestor import FileManifestIngestor, ImageManifestIngestor, IngestResult
from app.services.seed_manifest import generate_manifest
from app.tasks.enrich_manifest import enrich_manifest_packages
from app.tasks.run_sort_task import run_zone_sort

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


class SortRunAccepted(BaseModel):
    """Immediate response from POST /sort/run — task has been queued."""
    task_id: str
    status: str   # always "queued"


class SortRunStatusResponse(BaseModel):
    """Response from GET /sort/run/status/{task_id}."""
    task_id: str
    status: str   # "running" | "done" | "tier1_failed" | "error"
    # Populated when status == "done":
    sort_date: Optional[date] = None
    package_count: Optional[int] = None
    outlier_count: Optional[int] = None
    cluster_count: Optional[int] = None
    tier1_passed: Optional[bool] = None
    was_forced: Optional[bool] = None
    zones_created: Optional[int] = None
    assignments: list[ClusterAssignmentOut] = []
    # Populated when status == "tier1_failed":
    flagged_bags: list[BagResultOut] = []
    # Populated when status == "error" or "tier1_failed":
    detail: Optional[str] = None
    http_status: Optional[int] = None


class ManifestPreviewRow(BaseModel):
    tba: str
    raw_address: Optional[str] = None        # original address from manifest
    normalised_address: Optional[str] = None
    block_key: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    bag_id: Optional[str] = None
    enriched: bool   # False when block_key is None (geocoding failed)
    geocode_reason: Optional[str] = None     # failure code when not enriched


class ManifestPreviewResponse(BaseModel):
    sort_date: date
    total_packages: int
    enriched_count: int
    failed_count: int
    page: int
    page_size: int
    total_pages: int
    preview_rows: list[ManifestPreviewRow]


class ManifestPackagePatchRequest(BaseModel):
    corrected_address: str


class ManifestPackagePatchResponse(BaseModel):
    tba: str
    raw_address: Optional[str] = None
    normalised_address: Optional[str] = None
    block_key: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    enriched: bool
    geocode_reason: Optional[str] = None


class SortPreviewAssignment(BaseModel):
    truck_id: str
    truck_name: str
    match_type: str
    workload_score: Optional[float] = None
    is_overflow: bool
    package_count: int
    outlier_count: int


class SortPreviewResponse(BaseModel):
    sort_date: date
    task_id: str
    package_count: int
    outlier_count: int
    cluster_count: int
    tier1_passed: bool
    was_forced: bool
    zones_created: int
    assignments: list[SortPreviewAssignment]


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
    # Delete the old manifest key immediately so re-uploads never serve stale data
    # while the new enrichment is still in flight.
    r = _redis()
    r.delete(_manifest_key(cid_str, date_str))
    r.delete(f"manifest_progress:{cid_str}:{date_str}")
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

    # Enriching sentinel takes priority over stale cached data. Without this check,
    # a re-upload for the same date would immediately return "ready" with the old
    # manifest key still in Redis before the new enrichment task finishes.
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


_PREVIEW_PAGE_SIZE = 50


@router.get("/manifest/{sort_date}/preview", response_model=ManifestPreviewResponse)
def get_manifest_preview(
    sort_date: date,
    page: int = 1,
    failed_only: bool = False,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
):
    """Return a paginated page of enriched packages for a given sort date.

    Query params:
      page        — 1-indexed page number (default 1)
      failed_only — when True, only return packages with block_key=None
    """
    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()
    raw = r.get(_manifest_key(cid_str, date_str))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No enriched manifest found for this date. Upload and enrich a manifest first.",
        )
    try:
        packages = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Manifest data is corrupted — re-upload the file.",
        )

    enriched_count = sum(1 for p in packages if p.get("block_key") is not None)
    failed_count = len(packages) - enriched_count

    visible = [p for p in packages if p.get("block_key") is None] if failed_only else packages
    total_pages = max(1, (len(visible) + _PREVIEW_PAGE_SIZE - 1) // _PREVIEW_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PREVIEW_PAGE_SIZE
    page_items = visible[start: start + _PREVIEW_PAGE_SIZE]

    preview_rows = [
        ManifestPreviewRow(
            tba=p.get("tba", ""),
            raw_address=p.get("raw_address"),
            normalised_address=p.get("normalised_address"),
            block_key=p.get("block_key"),
            lat=p.get("lat"),
            lng=p.get("lng"),
            bag_id=p.get("bag_id"),
            enriched=p.get("block_key") is not None,
            geocode_reason=p.get("geocode_reason"),
        )
        for p in page_items
    ]

    return ManifestPreviewResponse(
        sort_date=sort_date,
        total_packages=len(packages),
        enriched_count=enriched_count,
        failed_count=failed_count,
        page=page,
        page_size=_PREVIEW_PAGE_SIZE,
        total_pages=total_pages,
        preview_rows=preview_rows,
    )


@router.patch(
    "/manifest/{sort_date}/package/{tba}",
    response_model=ManifestPackagePatchResponse,
    status_code=status.HTTP_200_OK,
)
def patch_manifest_package(
    sort_date: date,
    tba: str,
    body: ManifestPackagePatchRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
):
    """Re-geocode a single failed package with a corrected address.

    Reads the enriched manifest from Redis, finds the package by TBA,
    re-runs GeoClient + derive_block_key with the corrected address, updates
    the package in-place, and writes the manifest back to Redis.

    Only updates the package in the Redis cache — the DB is not touched until
    sort runs. If GeoClient still cannot resolve the address, the package
    remains failed (block_key=None) and the response reflects that.
    """
    from app.tasks.enrich_manifest import _geoclient_normalise
    from app.services.derive_block_key import derive_block_key, ParsedBlock
    from app.models.company import CompanyConfig

    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()
    key = _manifest_key(cid_str, date_str)
    raw = r.get(key)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No enriched manifest found for this date.",
        )
    try:
        packages: list[dict] = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Manifest data corrupted.")

    # Find the package
    pkg_index = next((i for i, p in enumerate(packages) if p.get("tba") == tba), None)
    if pkg_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"TBA {tba} not found in manifest.")

    # Resolve borough for this company
    from app.database import get_db as _get_db
    db_gen = _get_db()
    db = next(db_gen)
    try:
        cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
        borough = (cfg.geoclient_borough if cfg and cfg.geoclient_borough else None) or "manhattan"
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    address = body.corrected_address.strip()
    geo = _geoclient_normalise(address, borough=borough)

    block_key: Optional[str] = None
    normalised_address: Optional[str] = None
    lat = packages[pkg_index].get("lat")
    lng = packages[pkg_index].get("lng")

    if geo:
        normalised_address = geo.normalised_address
        if geo.lat is not None:
            lat = geo.lat
        if geo.lng is not None:
            lng = geo.lng
        bk = derive_block_key(geo.normalised_address, tba=tba)
        if isinstance(bk, ParsedBlock):
            block_key = bk.block_key

    # Update the package in-place and write back to Redis (preserve existing TTL).
    # Preserve raw_address (original manifest value) and clear geocode_reason on success.
    failure_reason = None if block_key else "geoclient_no_match"
    ttl = r.ttl(key)
    packages[pkg_index] = {
        **packages[pkg_index],
        "raw_address":        packages[pkg_index].get("raw_address") or address,
        "normalised_address": normalised_address,
        "block_key":          block_key,
        "lat":                lat,
        "lng":                lng,
        "geocode_reason":     failure_reason,
    }
    r.setex(key, max(ttl, _REDIS_TTL_SECONDS), json.dumps(packages))

    logger.info(
        "manifest_package_patched",
        extra={
            "company_id": cid_str,
            "sort_date":  date_str,
            "tba":        tba,
            "resolved":   block_key is not None,
        },
    )

    return ManifestPackagePatchResponse(
        tba=tba,
        raw_address=packages[pkg_index].get("raw_address"),
        normalised_address=normalised_address,
        block_key=block_key,
        lat=lat,
        lng=lng,
        enriched=block_key is not None,
        geocode_reason=failure_reason,
    )


_SORT_RUN_RUNNING_TTL = 300   # 5-min sentinel written at dispatch time


@router.post("/run", response_model=SortRunAccepted, status_code=status.HTTP_202_ACCEPTED)
def run_sort_endpoint(
    body: SortRunRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Queue the manifest sort pipeline for the given date.

    Returns immediately with a task_id. The caller polls
    GET /sort/run/status/{task_id} to retrieve the result.

    Override validation runs synchronously before queuing so the caller
    gets an immediate 400 rather than a delayed task failure.
    """
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

    task_id = str(_uuid_mod.uuid4())
    cid_str = str(caller.company_id)
    date_str = body.sort_date.isoformat()

    # Write running sentinel before dispatching — status endpoint returns "running"
    # immediately even before the worker picks up the task.
    r = _redis()
    from app.tasks.run_sort_task import _running_key, _failed_key
    r.setex(_running_key(cid_str, date_str, task_id), _SORT_RUN_RUNNING_TTL, "1")
    # Pre-write worker_unreachable so status returns "error" if the task is never picked up
    r.setex(_failed_key(cid_str, date_str, task_id), _REDIS_TTL_SECONDS, json.dumps({"detail": "worker_unreachable"}))

    # Strip raw_address from every package before sort runs — it served its purpose
    # in the dispatch correction window and must not persist beyond this point.
    manifest_key = _manifest_key(cid_str, date_str)
    manifest_raw = r.get(manifest_key)
    if manifest_raw:
        try:
            packages = json.loads(manifest_raw)
            for pkg in packages:
                pkg.pop("raw_address", None)
            ttl = r.ttl(manifest_key)
            r.setex(manifest_key, max(ttl, _REDIS_TTL_SECONDS), json.dumps(packages))
        except (json.JSONDecodeError, AttributeError):
            pass  # manifest already gone or malformed — sort will surface the error

    overrides_raw = [{"bag_id": ov.bag_id, "truck_id": str(ov.truck_id)} for ov in body.overrides]

    run_zone_sort.delay(
        company_id      = cid_str,
        sort_date       = date_str,
        task_id         = task_id,
        overrides       = overrides_raw,
        created_by      = str(caller.id),
        created_by_name = caller.name,
        force           = body.force,
    )

    logger.info(
        "sort run queued",
        extra={
            "company_id": cid_str,
            "sort_date":  date_str,
            "task_id":    task_id,
            "force":      body.force,
            "overrides":  len(body.overrides),
        },
    )

    return SortRunAccepted(task_id=task_id, status="queued")


@router.get("/run/status/{task_id}", response_model=SortRunStatusResponse)
def get_sort_run_status(
    task_id: str,
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
):
    """Poll the status of a queued sort run.

    Returns:
      status="running"      — task picked up but not yet complete
      status="done"         — zones persisted; full result included
      status="tier1_failed" — bags flagged; flagged_bags included for override UI
      status="error"        — unrecoverable error; detail included
    """
    from app.tasks.run_sort_task import _running_key, _result_key, _failed_key

    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()

    result_raw = r.get(_result_key(cid_str, date_str, task_id))
    if result_raw:
        try:
            data = json.loads(result_raw)
        except json.JSONDecodeError:
            return SortRunStatusResponse(task_id=task_id, status="error", detail="Result data corrupted.")

        s = data.get("status", "error")

        if s == "done":
            return SortRunStatusResponse(
                task_id       = task_id,
                status        = "done",
                sort_date     = date.fromisoformat(data["sort_date"]),
                package_count = data["package_count"],
                outlier_count = data["outlier_count"],
                cluster_count = data["cluster_count"],
                tier1_passed  = data["tier1_passed"],
                was_forced    = data["was_forced"],
                zones_created = data["zones_created"],
                assignments   = [ClusterAssignmentOut(**a) for a in data.get("assignments", [])],
                flagged_bags  = [],
            )

        if s == "tier1_failed":
            return SortRunStatusResponse(
                task_id      = task_id,
                status       = "tier1_failed",
                detail       = data.get("detail"),
                http_status  = data.get("http_status"),
                flagged_bags = [BagResultOut(**b) for b in data.get("flagged_bags", [])],
            )

        # "error" or unknown
        return SortRunStatusResponse(
            task_id     = task_id,
            status      = "error",
            detail      = data.get("detail"),
            http_status = data.get("http_status"),
        )

    running = r.exists(_running_key(cid_str, date_str, task_id))
    if running:
        return SortRunStatusResponse(task_id=task_id, status="running")

    failed_raw = r.get(_failed_key(cid_str, date_str, task_id))
    if failed_raw:
        try:
            data = json.loads(failed_raw)
            detail = data.get("detail", "Sort task failed unexpectedly.")
        except (json.JSONDecodeError, AttributeError):
            detail = "Sort task failed unexpectedly."
        if detail == "worker_unreachable":
            detail = "Sort task was not received by the worker — Celery may be down. Contact your admin."
        return SortRunStatusResponse(task_id=task_id, status="error", detail=detail)

    return SortRunStatusResponse(task_id=task_id, status="error", detail="Sort task result not found — it may have expired.")


@router.get("/run/preview/{task_id}", response_model=SortPreviewResponse)
def get_sort_run_preview(
    task_id: str,
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
):
    """Return a summary preview of a completed sort run.

    Only available when status is "done". Includes per-zone assignment breakdown
    with package counts and workload scores so dispatch can review before committing
    routes per truck.
    """
    from app.tasks.run_sort_task import _result_key

    cid_str = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()

    raw = r.get(_result_key(cid_str, date_str, task_id))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sort result not found — run sort first or result may have expired.",
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Sort result data corrupted.")

    if data.get("status") != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sort is not complete (status={data.get('status')}). Preview is only available after a successful sort.",
        )

    return SortPreviewResponse(
        sort_date     = date.fromisoformat(data["sort_date"]),
        task_id       = task_id,
        package_count = data["package_count"],
        outlier_count = data["outlier_count"],
        cluster_count = data["cluster_count"],
        tier1_passed  = data["tier1_passed"],
        was_forced    = data["was_forced"],
        zones_created = data["zones_created"],
        assignments   = [
            SortPreviewAssignment(
                truck_id      = a["truck_id"],
                truck_name    = a["truck_name"],
                match_type    = a["match_type"],
                workload_score= a.get("workload_score"),
                is_overflow   = a["is_overflow"],
                package_count = a["package_count"],
                outlier_count = data["outlier_count"],
            )
            for a in data.get("assignments", [])
        ],
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
