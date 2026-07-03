"""Sort router — manifest sort pipeline endpoints.

POST /sort/upload            — upload CSV/XLSX/PDF/image manifest, trigger async enrichment
GET  /sort/manifest/{date}/status — poll enrichment status (ready / enriching / not_found)
POST /sort/run               — run the full sort pipeline for a given date
GET  /sort/{date}            — fetch existing zone results for a date
GET  /sort/{date}/centroids  — fetch route cluster centroids for the Deck.gl density layer
"""
from __future__ import annotations

import csv
import io
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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.company import CompanyConfig, CompanyZone
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


class BagPackageDetail(BaseModel):
    tba: str
    tag_number: Optional[str] = None
    normalised_address: Optional[str] = None


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
    outside_packages_detail: list[BagPackageDetail] = []


class ClusterAssignmentOut(BaseModel):
    truck_id: UUID
    truck_name: str
    match_type: str
    anchor_source: Optional[str] = None   # "truck_anchor" | "zone_history" | "building_profile" | "quantile"
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
    volume_alert: bool = False
    volume_alert_msg: str = ""
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
    volume_alert: Optional[bool] = None
    volume_alert_msg: Optional[str] = None
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
    anchor_source: Optional[str] = None
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
    volume_alert: bool = False
    volume_alert_msg: str = ""
    assignments: list[SortPreviewAssignment]


class ZoneOut(BaseModel):
    id: UUID
    truck_id: UUID
    zone_label: str
    truck_polygon: list[dict]
    zone_date: date
    is_active: bool
    tote_count: Optional[int] = None      # distinct totes in this zone (null on pre-ADR-169 rows)
    package_count: int = 0                # len(package_tbas) — computed at read time
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


@router.get("/manifest/{sort_date}/download")
def download_enriched_manifest(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Download the full enriched manifest for a sort date as CSV.

    Includes every field stored in Redis: tba, bag_id, raw_address,
    normalised_address, block_key, lat, lng, geocode_reason.
    Dispatch/management/admin only — same gate as the preview endpoint.
    """
    cid_str  = str(caller.company_id)
    date_str = sort_date.isoformat()
    r = _redis()
    raw = r.get(_manifest_key(cid_str, date_str))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No enriched manifest found for this date.",
        )
    packages = json.loads(raw)

    fields = ["tba", "bag_id", "raw_address", "normalised_address",
              "block_key", "lat", "lng", "geocode_reason"]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for p in packages:
        writer.writerow({f: p.get(f, "") for f in fields})

    buf.seek(0)
    filename = f"enriched_manifest_{date_str}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
                task_id          = task_id,
                status           = "done",
                sort_date        = date.fromisoformat(data["sort_date"]),
                package_count    = data["package_count"],
                outlier_count    = data["outlier_count"],
                cluster_count    = data["cluster_count"],
                tier1_passed     = data["tier1_passed"],
                was_forced       = data["was_forced"],
                zones_created    = data["zones_created"],
                volume_alert     = data.get("volume_alert", False),
                volume_alert_msg = data.get("volume_alert_msg", ""),
                assignments      = [ClusterAssignmentOut(**a) for a in data.get("assignments", [])],
                flagged_bags     = [],
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
        _SENTINEL_MESSAGES = {
            "internal_error":    "Zone assignment failed due to an unexpected error. Check worker logs and retry.",
            "worker_unreachable": "Sort task was not received by the worker — Celery may be down. Contact your admin.",
        }
        raw_detail = data.get("detail")
        return SortRunStatusResponse(
            task_id     = task_id,
            status      = "error",
            detail      = _SENTINEL_MESSAGES.get(raw_detail, raw_detail),
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
        elif detail == "internal_error":
            detail = "Zone assignment failed due to an unexpected error. Check worker logs and retry."
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
        sort_date        = date.fromisoformat(data["sort_date"]),
        task_id          = task_id,
        package_count    = data["package_count"],
        outlier_count    = data["outlier_count"],
        cluster_count    = data["cluster_count"],
        tier1_passed     = data["tier1_passed"],
        was_forced       = data["was_forced"],
        zones_created    = data["zones_created"],
        volume_alert     = data.get("volume_alert", False),
        volume_alert_msg = data.get("volume_alert_msg", ""),
        assignments      = [
            SortPreviewAssignment(
                truck_id       = a["truck_id"],
                truck_name     = a["truck_name"],
                match_type     = a["match_type"],
                anchor_source  = a.get("anchor_source"),
                workload_score = a.get("workload_score"),
                is_overflow    = a["is_overflow"],
                package_count  = a["package_count"],
                outlier_count  = data["outlier_count"],
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


# ---------------------------------------------------------------------------
# Company operating zone — must be declared before /{sort_date} routes so
# FastAPI does not greedily match /company-zone as a date path parameter.
# ---------------------------------------------------------------------------

class OperatingZoneIn(BaseModel):
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float
    name: str = "Operating Zone"


class OperatingZoneFromStreetsIn(BaseModel):
    from_street: str = Field(..., max_length=100, description="Starting cross-street, e.g. 'W 23 St'")
    to_street:   str = Field(..., max_length=100, description="Ending cross-street, e.g. 'W 57 St'")
    from_avenue: str = Field(..., max_length=100, description="Starting avenue, e.g. '6 Ave'")
    to_avenue:   str = Field(..., max_length=100, description="Ending avenue, e.g. '12 Ave'")
    borough:     str = Field("manhattan", max_length=30)
    name:        str = Field("Operating Zone", max_length=100)


class IntersectionIn(BaseModel):
    street: str = Field(..., max_length=100)
    avenue: str = Field(..., max_length=100)


class OperatingZoneFromIntersectionsIn(BaseModel):
    intersections: list[IntersectionIn] = Field(..., min_length=3, max_length=50)
    borough: str = Field("manhattan", max_length=30)
    name:    str = Field("Operating Zone", max_length=100)


class OperatingZoneFromCornersIn(BaseModel):
    corners: list[CornerPoint] = Field(..., min_length=3, max_length=50)
    name:    str = Field("Operating Zone", max_length=100)


class CornerPoint(BaseModel):
    lat: float
    lng: float


class OperatingZoneOut(BaseModel):
    id: UUID
    name: str
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float
    corners: list[CornerPoint] = []

    model_config = ConfigDict(from_attributes=True)


def _corners_to_geojson(corners: list[tuple[float, float]]) -> dict:
    """Convert an ordered list of (lat, lng) corner points to a closed GeoJSON Polygon ring."""
    ring = [[lng, lat] for lat, lng in corners]
    ring.append(ring[0])   # close the ring
    return {"type": "Polygon", "coordinates": [ring]}


def _bbox_to_geojson(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float) -> dict:
    """Convert SW/NE corners to a closed GeoJSON Polygon rectangle (AABB — 4 axis-aligned corners)."""
    return _corners_to_geojson([
        (sw_lat, sw_lng),
        (sw_lat, ne_lng),
        (ne_lat, ne_lng),
        (ne_lat, sw_lng),
    ])


def _geojson_to_bbox(bounds: dict) -> tuple[float, float, float, float] | None:
    """Extract SW/NE AABB corners from a GeoJSON Polygon (used by sort algorithm for fast containment check)."""
    try:
        coords = bounds["coordinates"][0]
        lngs = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return min(lats), min(lngs), max(lats), max(lngs)
    except (KeyError, IndexError, TypeError):
        return None


def _geojson_to_corners(bounds: dict) -> list[CornerPoint]:
    """Return the actual polygon vertices (excluding the closing duplicate) as CornerPoint list."""
    try:
        coords = bounds["coordinates"][0]
        pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
        return [CornerPoint(lat=c[1], lng=c[0]) for c in pts]
    except (KeyError, IndexError, TypeError):
        return []


@router.get("/geoclient-probe")
def geoclient_probe(
    street_one: str = "W 23 ST",
    street_two: str = "6 AVE",
    borough: str = "manhattan",
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
):
    """Admin-only probe: returns the raw GeoClient v2 response for an intersection."""
    import requests as _requests

    if not settings.geoclient_app_key:
        return {"error": "GEOCLIENT_APP_KEY is not set on this server."}

    results = {}
    for path in ("/intersection.json", "/intersection"):
        try:
            resp = _requests.get(
                f"{_GEOCLIENT_BASE}{path}",
                params={"crossStreetOne": street_one, "crossStreetTwo": street_two, "borough": borough},
                headers={"Ocp-Apim-Subscription-Key": settings.geoclient_app_key},
                timeout=5,
            )
            results[path] = {"status": resp.status_code, "body": resp.json() if resp.ok else resp.text[:500]}
        except Exception as exc:
            results[path] = {"error": type(exc).__name__}

    return results


@router.get("/company-zone", response_model=Optional[OperatingZoneOut])
def get_company_zone(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Return the company's operating zone bounding box, or null if not configured."""
    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == caller.company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .order_by(CompanyZone.created_at.desc())
        .first()
    )
    if zone is None or not zone.bounds:
        return None
    bbox = _geojson_to_bbox(zone.bounds)
    if bbox is None:
        return None
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(zone.bounds),
    )


@router.post("/company-zone", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone(
    body: OperatingZoneIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company's operating zone from a SW/NE bounding box."""
    from datetime import datetime, timezone
    from app.services.audit import write_audit

    if body.sw_lat >= body.ne_lat:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="SW latitude must be less than NE latitude.")
    if body.sw_lng >= body.ne_lng:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="SW longitude must be less than NE longitude.")

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session="fetch")

    bounds = _bbox_to_geojson(body.sw_lat, body.sw_lng, body.ne_lat, body.ne_lng)
    import uuid as _uuid
    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"sw_lat": body.sw_lat, "sw_lng": body.sw_lng, "ne_lat": body.ne_lat, "ne_lng": body.ne_lng},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=body.sw_lat,
        sw_lng=body.sw_lng,
        ne_lat=body.ne_lat,
        ne_lng=body.ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/company-zone/from-streets", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_streets(
    body: OperatingZoneFromStreetsIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company's operating zone from street/avenue range inputs."""
    from app.tasks.enrich_manifest import _geoclient_intersection
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    if not settings.geoclient_app_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoClient API key is not configured on this server. Use the Advanced section to enter coordinates directly.",
        )

    from_st = body.from_street.strip()
    to_st   = body.to_street.strip()
    from_av = body.from_avenue.strip()
    to_av   = body.to_avenue.strip()

    corner_pairs = [
        (from_st, from_av),
        (from_st, to_av),
        (to_st,   from_av),
        (to_st,   to_av),
    ]
    # corner_pairs order: (from_st/from_av=SW, from_st/to_av=SE, to_st/from_av=NW, to_st/to_av=NE)
    geocoded: list[tuple[float, float]] = []
    for street, avenue in corner_pairs:
        result = _geoclient_intersection(street, avenue, borough=body.borough)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Could not geocode '{street} & {avenue}' in {body.borough}. "
                    f"Check the spelling — use formats like 'W 23 ST', '6 AVE', 'BROADWAY'."
                ),
            )
        geocoded.append(result)   # (lat, lng)

    # Build a proper quadrilateral from the 4 geocoded intersection points in geographic
    # order (SW → SE → NE → NW) so the polygon hugs the actual delivery area without
    # bleeding into water or adjacent territory the way an axis-aligned rectangle would.
    sw, se, nw, ne_pt = geocoded[0], geocoded[1], geocoded[2], geocoded[3]
    quad_corners = [sw, se, ne_pt, nw]

    lats = [p[0] for p in geocoded]
    lngs = [p[1] for p in geocoded]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    if sw_lat >= ne_lat or sw_lng >= ne_lng:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Derived bounding box is degenerate — check that from/to streets and avenues differ.",
        )

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session="fetch")

    # Store the exact quadrilateral — not the axis-aligned rectangle — so the frontend
    # can draw a polygon that matches the actual street grid boundaries.
    bounds = _corners_to_geojson(quad_corners)
    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={
            "from_street": from_st, "to_street": to_st,
            "from_avenue": from_av, "to_avenue": to_av,
            "sw_lat": sw_lat, "sw_lng": sw_lng,
            "ne_lat": ne_lat, "ne_lng": ne_lng,
        },
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/company-zone/from-intersections", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_intersections(
    body: OperatingZoneFromIntersectionsIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company zone from an ordered list of street+avenue intersections.

    Each intersection is geocoded in order; the resulting lat/lng points form the polygon
    vertices. Minimum 3 intersections required to define a valid polygon.
    """
    from app.tasks.enrich_manifest import _geoclient_intersection
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    if not settings.geoclient_app_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoClient API key is not configured. Use draw mode or raw coordinates instead.",
        )

    geocoded: list[tuple[float, float]] = []
    for ix in body.intersections:
        result = _geoclient_intersection(ix.street.strip(), ix.avenue.strip(), borough=body.borough)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Could not geocode '{ix.street} & {ix.avenue}' in {body.borough}. "
                    f"Use formats like 'W 23 ST', '6 AVE', 'BROADWAY'."
                ),
            )
        geocoded.append(result)

    lats = [p[0] for p in geocoded]
    lngs = [p[1] for p in geocoded]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    bounds = _corners_to_geojson(geocoded)

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session="fetch")

    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"method": "intersections", "count": len(geocoded), "borough": body.borough},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/company-zone/from-corners", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_corners(
    body: OperatingZoneFromCornersIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company zone from raw lat/lng corner points (click-to-draw output)."""
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    lats = [c.lat for c in body.corners]
    lngs = [c.lng for c in body.corners]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    bounds = _corners_to_geojson([(c.lat, c.lng) for c in body.corners])

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session="fetch")

    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"method": "draw", "vertex_count": len(body.corners)},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )


# ---------------------------------------------------------------------------
# Per-date sort status routes — /{sort_date} must come after all literal paths
# ---------------------------------------------------------------------------

class OutlierToteOut(BaseModel):
    """A tote whose packages the sort could not place in any zone."""
    tote_id: str                       # bag_id, or "(loose)" for bagless packages
    centroid_lat: Optional[float] = None   # None when no package in the tote geocoded
    centroid_lng: Optional[float] = None
    package_count: int
    tba_numbers: list[str]


class OutlierTotesResponse(BaseModel):
    sort_date: date
    totes: list[OutlierToteOut]
    manifest_available: bool           # False once the Redis manifest has expired


@router.get("/{sort_date}/outlier-totes", response_model=OutlierTotesResponse)
def get_outlier_totes(
    sort_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Totes left out of every zone for this date (ADR-169 outlier totes).

    Derived on the fly: all manifest TBAs minus the TBAs present in the
    active TruckZones, grouped back into totes by bag_id. These are the red
    markers on the dispatch map — out-of-territory or un-geocodable totes
    that need a manual decision (reassign-tbas or ignore).

    Only meaningful while the enriched manifest is still in Redis (24h TTL);
    afterwards returns manifest_available=False with an empty list.
    """
    zones = (
        db.query(TruckZone)
        .filter(
            TruckZone.company_id == caller.company_id,
            TruckZone.zone_date == sort_date,
            TruckZone.is_active.is_(True),
        )
        .all()
    )
    assigned: set[str] = {tba for z in zones for tba in (z.package_tbas or [])}

    raw = _redis().get(_manifest_key(str(caller.company_id), sort_date.isoformat()))
    if raw is None:
        return OutlierTotesResponse(sort_date=sort_date, totes=[], manifest_available=False)
    try:
        packages = json.loads(raw)
    except json.JSONDecodeError:
        return OutlierTotesResponse(sort_date=sort_date, totes=[], manifest_available=False)

    # No zones yet → nothing is an "outlier", everything is just unsorted.
    if not zones:
        return OutlierTotesResponse(sort_date=sort_date, totes=[], manifest_available=True)

    grouped: dict[str, list[dict]] = {}
    for pkg in packages:
        tba = pkg.get("tba")
        if not tba or tba in assigned:
            continue
        key = pkg.get("bag_id") or "(loose)"
        grouped.setdefault(key, []).append(pkg)

    totes: list[OutlierToteOut] = []
    for tote_id, pkgs in grouped.items():
        coord = [p for p in pkgs if p.get("lat") is not None and p.get("lng") is not None]
        totes.append(OutlierToteOut(
            tote_id       = tote_id,
            centroid_lat  = sum(p["lat"] for p in coord) / len(coord) if coord else None,
            centroid_lng  = sum(p["lng"] for p in coord) / len(coord) if coord else None,
            package_count = len(pkgs),
            tba_numbers   = [p["tba"] for p in pkgs],
        ))
    totes.sort(key=lambda t: -t.package_count)

    return OutlierTotesResponse(sort_date=sort_date, totes=totes, manifest_available=True)


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
        zones      = [
            ZoneOut(
                id            = z.id,
                truck_id      = z.truck_id,
                zone_label    = z.zone_label,
                truck_polygon = z.truck_polygon,
                zone_date     = z.zone_date,
                is_active     = z.is_active,
                tote_count    = z.tote_count,
                package_count = len(z.package_tbas or []),
            )
            for z in zones
        ],
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

    # Keep tote_count consistent with the new membership (ADR-169 equity display).
    # Bag grouping comes from the Redis manifest; if it has expired we cannot
    # know which bags the moved TBAs belong to — set None (unknown) rather than
    # leave a stale number.
    def _recount_totes(tbas: list[str]) -> Optional[int]:
        raw = _redis().get(_manifest_key(str(caller.company_id), source.zone_date.isoformat()))
        if raw is None:
            return None
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            return None
        tba_bag = {p.get("tba"): p.get("bag_id") for p in manifest if p.get("tba")}
        bags: set[str] = set()
        loose = 0
        for t in tbas:
            b = tba_bag.get(t)
            if b:
                bags.add(b)
            else:
                loose += 1
        return len(bags) + loose

    source.tote_count      = _recount_totes(updated_source_tbas)
    destination.tote_count = _recount_totes(updated_dest_tbas)

    # Keep tote_roster consistent with the moved TBAs (ADR-174): remove them
    # from source entries (dropping emptied entries) and merge them into the
    # destination's entry for the same bag (creating a partial entry if the
    # bag isn't there yet). Entry-level OV/dock fields describe the whole bag
    # and are left as-is — they remain the physical bag's locator data.
    def _roster_remove(roster, tbas: set):
        out = []
        for e in (roster or []):
            kept = [t for t in e.get("tba_numbers", []) if t not in tbas]
            if not kept:
                continue
            if len(kept) != len(e.get("tba_numbers", [])):
                e = {**e, "tba_numbers": kept, "package_count": len(kept)}
            out.append(e)
        return out

    def _roster_add(roster, source_roster, tbas: list):
        by_bag: dict = {}
        for t in tbas:
            src_entry = next((e for e in (source_roster or []) if t in e.get("tba_numbers", [])), None)
            bag = src_entry["bag_id"] if src_entry else f"(loose) {t}"
            by_bag.setdefault(bag, {"entry": src_entry, "tbas": []})["tbas"].append(t)
        out = list(roster or [])
        for bag, info in by_bag.items():
            existing = next((e for e in out if e["bag_id"] == bag), None)
            if existing is not None:
                merged = existing.get("tba_numbers", []) + info["tbas"]
                out = [
                    {**e, "tba_numbers": merged, "package_count": len(merged)} if e["bag_id"] == bag else e
                    for e in out
                ]
            else:
                base = info["entry"] or {"bag_id": bag, "ov_count": 0, "ov_sizes": [], "dock_tags": [], "ov_dock_tags": []}
                out.append({**base, "bag_id": bag, "tba_numbers": info["tbas"], "package_count": len(info["tbas"])})
        out.sort(key=lambda r: (r["dock_tags"][0] if r.get("dock_tags") else "~", r["bag_id"]))
        return out

    original_source_roster = source.tote_roster
    destination.tote_roster = _roster_add(destination.tote_roster, original_source_roster, tbas_to_move)
    source.tote_roster      = _roster_remove(original_source_roster, tbas_to_move_set)

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


# ── Company operating zone ────────────────────────────────────────────────────


# ── Station load finalization: rosters, check-off, transfers (ADR-174) ────────

class ToteTransferOut(BaseModel):
    id: UUID
    bag_id: str
    from_truck_id: UUID
    from_truck_name: str
    from_driver_name: Optional[str] = None
    to_truck_id: UUID
    to_truck_name: str
    to_driver_name: Optional[str] = None
    package_count: Optional[int] = None
    status: str          # suggested | confirmed | completed | kept
    reason: str          # rerun_diff | dispatch


class OvDetailOut(BaseModel):
    size: str                      # OV_S | OV_M | OV_L | OV_XL
    zone: Optional[str] = None     # OV sort zone on the dock (from the manifest)


class RosterToteOut(BaseModel):
    bag_id: str
    package_count: int
    ov_count: int
    ov_sizes: list[str]
    ov_details: list[OvDetailOut] = []
    dock_tags: list[str]
    ov_dock_tags: list[str]
    classification: str = "clean"  # clean | stray | uncertain | misaligned (tier-1)
    checked: bool
    checked_by_name: Optional[str] = None
    transfer: Optional[ToteTransferOut] = None   # transfer touching this bag (incl. kept, for undo)


class TruckRosterOut(BaseModel):
    zone_id: UUID
    truck_id: UUID
    zone_label: str
    driver_name: Optional[str] = None
    totes: list[RosterToteOut]
    tote_count: int
    checked_count: int
    incoming: list[ToteTransferOut]
    outgoing: list[ToteTransferOut]


class RostersResponse(BaseModel):
    sort_date: date
    rosters: list[TruckRosterOut]
    pending_transfer_count: int
    unchecked_count: int
    loading_finalized: bool       # soft gate — informational only (ADR-174 decision b)
    roster_available: bool        # False when zones predate roster persistence


def _driver_names_by_truck(db: Session, company_id, sort_date: date) -> dict:
    """truck_id → driver display name for the date's crews."""
    from app.models.assignment_member import AssignmentMember
    rows = (
        db.query(TruckAssignment.truck_id, Employee.name)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .join(Employee, Employee.id == AssignmentMember.employee_id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == sort_date,
            AssignmentMember.role == "driver",
        )
        .all()
    )
    return {truck_id: name for truck_id, name in rows}


def _caller_truck_id(db: Session, caller: Employee, sort_date: date):
    """The truck the caller crews on for the date, or None."""
    from app.models.assignment_member import AssignmentMember
    row = (
        db.query(TruckAssignment.truck_id)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == sort_date,
            AssignmentMember.employee_id == caller.id,
        )
        .first()
    )
    return row[0] if row else None


def _active_zones(db: Session, company_id, sort_date: date) -> list:
    return (
        db.query(TruckZone)
        .filter(
            TruckZone.company_id == company_id,
            TruckZone.zone_date == sort_date,
            TruckZone.is_active.is_(True),
        )
        .order_by(TruckZone.zone_label)
        .all()
    )


def _transfer_out(t, truck_names: dict, drivers: dict) -> "ToteTransferOut":
    return ToteTransferOut(
        id=t.id,
        bag_id=t.bag_id,
        from_truck_id=t.from_truck_id,
        from_truck_name=truck_names.get(t.from_truck_id, "?"),
        from_driver_name=drivers.get(t.from_truck_id),
        to_truck_id=t.to_truck_id,
        to_truck_name=truck_names.get(t.to_truck_id, "?"),
        to_driver_name=drivers.get(t.to_truck_id),
        package_count=t.package_count,
        status=t.status,
        reason=t.reason,
    )


@router.get("/{sort_date}/rosters", response_model=RostersResponse)
def get_load_rosters(
    sort_date: date,
    mine: bool = False,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["driver", "trainer", "dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Per-truck tote rosters with check-off state and station transfers.

    Dispatch/management/admin see every truck; drivers and trainers are always
    scoped to their own crewed truck (the `mine` flag is implied for them).
    This is the payload AP Sort consumes: once loading_finalized is true, the
    physical truck contents match TruckZone exactly. Soft gate — the flag warns,
    nothing is blocked (ADR-174).
    """
    from app.models.tote_ops import ToteTransfer, ToteLoadCheck

    zones = _active_zones(db, caller.company_id, sort_date)
    truck_names = {
        t.id: t.name
        for t in db.query(Truck).filter(Truck.company_id == caller.company_id).all()
    }
    drivers = _driver_names_by_truck(db, caller.company_id, sort_date)

    scope_truck = None
    if mine or caller.role in ("driver", "trainer"):
        scope_truck = _caller_truck_id(db, caller, sort_date)
        if scope_truck is None and caller.role in ("driver", "trainer"):
            return RostersResponse(
                sort_date=sort_date, rosters=[], pending_transfer_count=0,
                unchecked_count=0, loading_finalized=False, roster_available=False,
            )

    checks = {
        c.bag_id: c
        for c in db.query(ToteLoadCheck).filter(
            ToteLoadCheck.company_id == caller.company_id,
            ToteLoadCheck.load_date == sort_date,
        ).all()
    }
    transfers = (
        db.query(ToteTransfer)
        .filter(
            ToteTransfer.company_id == caller.company_id,
            ToteTransfer.transfer_date == sort_date,
        )
        .all()
    )
    # kept is included so the row can show the decision and offer undo;
    # incoming/outgoing lists below stay limited to actionable moves.
    active_transfer_by_bag = {
        t.bag_id: t for t in transfers if t.status in ("suggested", "confirmed", "kept")
    }

    rosters: list[TruckRosterOut] = []
    total_unchecked = 0
    roster_available = False
    for z in zones:
        roster = z.tote_roster or []
        if roster:
            roster_available = True
        totes: list[RosterToteOut] = []
        checked_count = 0
        for entry in roster:
            chk = checks.get(entry["bag_id"])
            if chk:
                checked_count += 1
            xfer = active_transfer_by_bag.get(entry["bag_id"])
            totes.append(RosterToteOut(
                bag_id=entry["bag_id"],
                package_count=entry.get("package_count", len(entry.get("tba_numbers", []))),
                ov_count=entry.get("ov_count", 0),
                ov_sizes=entry.get("ov_sizes", []),
                ov_details=[OvDetailOut(**d) for d in entry.get("ov_details", [])],
                dock_tags=entry.get("dock_tags", []),
                ov_dock_tags=entry.get("ov_dock_tags", []),
                classification=entry.get("classification", "clean"),
                checked=chk is not None,
                checked_by_name=chk.checked_by_name if chk else None,
                transfer=_transfer_out(xfer, truck_names, drivers) if xfer else None,
            ))
        total_unchecked += len(roster) - checked_count
        rosters.append(TruckRosterOut(
            zone_id=z.id,
            truck_id=z.truck_id,
            zone_label=z.zone_label,
            driver_name=drivers.get(z.truck_id),
            totes=totes,
            tote_count=z.tote_count if z.tote_count is not None else len(roster),
            checked_count=checked_count,
            incoming=[
                _transfer_out(t, truck_names, drivers)
                for t in transfers
                if t.to_truck_id == z.truck_id and t.status in ("suggested", "confirmed")
            ],
            outgoing=[
                _transfer_out(t, truck_names, drivers)
                for t in transfers
                if t.from_truck_id == z.truck_id and t.status in ("suggested", "confirmed")
            ],
        ))

    if scope_truck is not None:
        rosters = [r for r in rosters if r.truck_id == scope_truck]

    pending = sum(1 for t in transfers if t.status in ("suggested", "confirmed"))
    return RostersResponse(
        sort_date=sort_date,
        rosters=rosters,
        pending_transfer_count=pending,
        unchecked_count=total_unchecked,
        loading_finalized=roster_available and pending == 0 and total_unchecked == 0,
        roster_available=roster_available,
    )


class ToteCheckRequest(BaseModel):
    checked: bool     # true = check off, false = un-check


@router.post("/{sort_date}/totes/{bag_id}/check", response_model=RostersResponse)
def check_tote(
    sort_date: date,
    bag_id: str,
    body: ToteCheckRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["driver", "trainer", "dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Check a tote onto (or off) its assigned truck during station loading.

    Drivers/trainers may only check totes on their own crewed truck. Checking
    the destination tote of a confirmed transfer completes the transfer.
    Returns the refreshed rosters payload so the UI stays consistent.
    """
    from datetime import datetime, timezone
    from app.models.audit_log import AuditLog
    from app.models.tote_ops import ToteTransfer, ToteLoadCheck

    zones = _active_zones(db, caller.company_id, sort_date)
    home_zone = next((z for z in zones if any(e["bag_id"] == bag_id for e in (z.tote_roster or []))), None)
    if home_zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tote not found in any active zone for this date.")

    if caller.role in ("driver", "trainer"):
        own = _caller_truck_id(db, caller, sort_date)
        if own != home_zone.truck_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only check totes on your own truck.")

    existing = (
        db.query(ToteLoadCheck)
        .filter(
            ToteLoadCheck.company_id == caller.company_id,
            ToteLoadCheck.load_date == sort_date,
            ToteLoadCheck.bag_id == bag_id,
        )
        .first()
    )

    if body.checked:
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tote is already checked off.")
        db.add(ToteLoadCheck(
            id=_uuid_mod.uuid4(),
            company_id=caller.company_id,
            load_date=sort_date,
            truck_id=home_zone.truck_id,
            bag_id=bag_id,
            checked_by=caller.id,
            checked_by_name=caller.name,
        ))
        # A confirmed transfer completes when the tote lands on its destination.
        xfer = (
            db.query(ToteTransfer)
            .filter(
                ToteTransfer.company_id == caller.company_id,
                ToteTransfer.transfer_date == sort_date,
                ToteTransfer.bag_id == bag_id,
                ToteTransfer.status == "confirmed",
                ToteTransfer.to_truck_id == home_zone.truck_id,
            )
            .first()
        )
        if xfer is not None:
            xfer.status = "completed"
            xfer.completed_at = datetime.now(timezone.utc)
        action = "sort.tote_checked"
    else:
        if existing is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tote is not checked off.")
        db.delete(existing)
        action = "sort.tote_unchecked"

    db.flush()
    db.add(AuditLog(
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type=action,
        target_table="tote_load_checks",
        target_id=home_zone.id,
        after_snapshot={"bag_id": bag_id, "truck_id": str(home_zone.truck_id), "date": sort_date.isoformat()},
    ))
    db.commit()
    return get_load_rosters(sort_date=sort_date, mine=False, caller=caller, _={}, db=db)


def _move_bag_between_zones(db: Session, company_id, sort_date: date, bag_id: str, dest_truck_id) -> tuple:
    """Move a whole bag's roster entry + TBAs from its current zone to the
    destination truck's primary zone. Returns (src_zone, dest_zone)."""
    zones = _active_zones(db, company_id, sort_date)
    src = next((z for z in zones if any(e["bag_id"] == bag_id for e in (z.tote_roster or []))), None)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tote not found in any active zone for this date.")
    dest = next((z for z in zones if z.truck_id == dest_truck_id), None)
    if dest is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Destination truck has no active zone for this date.")
    if src.id == dest.id:
        return src, dest

    entry = next(e for e in src.tote_roster if e["bag_id"] == bag_id)
    moved_tbas = set(entry.get("tba_numbers", []))

    src.tote_roster  = [e for e in src.tote_roster if e["bag_id"] != bag_id]
    src.package_tbas = [t for t in (src.package_tbas or []) if t not in moved_tbas]
    src.tote_count   = len(src.tote_roster)

    dest_roster = list(dest.tote_roster or [])
    dest_roster.append(entry)
    dest_roster.sort(key=lambda r: (r["dock_tags"][0] if r.get("dock_tags") else "~", r["bag_id"]))
    dest.tote_roster  = dest_roster
    dest.package_tbas = list(dest.package_tbas or []) + sorted(moved_tbas)
    dest.tote_count   = len(dest_roster)
    return src, dest


class TransferResolveRequest(BaseModel):
    action: str   # "confirm" | "keep"


@router.post("/transfers/{transfer_id}/resolve", response_model=RostersResponse)
def resolve_transfer(
    transfer_id: UUID,
    body: TransferResolveRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Resolve a suggested station transfer.

    confirm — the tote will physically move; zone data already points at the
              destination (re-run diff), so nothing moves in the DB. Completion
              happens when the tote is checked off on the destination truck.
    keep    — the tote stays where it physically is; zone data is moved back to
              the from_truck so TruckZone matches reality again.
    """
    from datetime import datetime, timezone
    from app.models.audit_log import AuditLog
    from app.models.tote_ops import ToteTransfer

    if body.action not in ("confirm", "keep"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="action must be 'confirm' or 'keep'.")

    xfer = (
        db.query(ToteTransfer)
        .filter(ToteTransfer.id == transfer_id, ToteTransfer.company_id == caller.company_id)
        .first()
    )
    if xfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found.")
    if xfer.status != "suggested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Transfer is already {xfer.status}.")

    if body.action == "confirm":
        xfer.status = "confirmed"
    else:
        _move_bag_between_zones(db, caller.company_id, xfer.transfer_date, xfer.bag_id, xfer.from_truck_id)
        xfer.status = "kept"
    xfer.resolved_by = caller.id
    xfer.resolved_by_name = caller.name
    xfer.resolved_at = datetime.now(timezone.utc)

    db.flush()
    db.add(AuditLog(
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type=f"sort.transfer_{body.action}",
        target_table="tote_transfers",
        target_id=xfer.id,
        after_snapshot={"bag_id": xfer.bag_id, "from": str(xfer.from_truck_id), "to": str(xfer.to_truck_id)},
    ))
    db.commit()
    return get_load_rosters(sort_date=xfer.transfer_date, mine=False, caller=caller, _={}, db=db)


class ManualTransferRequest(BaseModel):
    to_truck_id: UUID


@router.post("/{sort_date}/totes/{bag_id}/transfer", response_model=RostersResponse)
def create_manual_transfer(
    sort_date: date,
    bag_id: str,
    body: ManualTransferRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Dispatch-initiated station transfer of a whole tote to another truck.

    Created directly as `confirmed` (dispatch initiating IS the confirmation);
    zone data moves immediately, and the transfer completes when the tote is
    checked off on the destination truck.
    """
    from app.models.audit_log import AuditLog
    from app.models.tote_ops import ToteTransfer

    pending = (
        db.query(ToteTransfer)
        .filter(
            ToteTransfer.company_id == caller.company_id,
            ToteTransfer.transfer_date == sort_date,
            ToteTransfer.bag_id == bag_id,
            ToteTransfer.status.in_(["suggested", "confirmed"]),
        )
        .first()
    )
    if pending is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This tote already has a pending transfer — resolve it first.")

    # Manual moves are restricted to totes tier-1 flagged (stray/uncertain/
    # misaligned). Clean totes sit exactly where the balanced sort wants them —
    # moving one silently degrades equity and geography; if the assignment is
    # wrong the fix is an anchor change + re-run, which produces reviewable
    # suggested transfers instead of ad-hoc moves.
    zones_for_class = _active_zones(db, caller.company_id, sort_date)
    entry_class = None
    for z in zones_for_class:
        for e in (z.tote_roster or []):
            if e["bag_id"] == bag_id:
                entry_class = e.get("classification", "clean")
                break
    if entry_class not in ("stray", "uncertain", "misaligned"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only totes flagged by tier-1 verification (stray, uncertain or misaligned) can be manually transferred. Re-run the sort to change clean assignments.",
        )

    src, dest = _move_bag_between_zones(db, caller.company_id, sort_date, bag_id, body.to_truck_id)
    if src.id == dest.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Tote is already on that truck.")

    entry_count = next((e["package_count"] for e in dest.tote_roster if e["bag_id"] == bag_id), None)
    xfer = ToteTransfer(
        id=_uuid_mod.uuid4(),
        company_id=caller.company_id,
        transfer_date=sort_date,
        bag_id=bag_id,
        from_truck_id=src.truck_id,
        to_truck_id=dest.truck_id,
        package_count=entry_count,
        status="confirmed",
        reason="dispatch",
        resolved_by=caller.id,
        resolved_by_name=caller.name,
    )
    db.add(xfer)
    db.flush()
    db.add(AuditLog(
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="sort.tote_transfer",
        target_table="tote_transfers",
        target_id=xfer.id,
        after_snapshot={"bag_id": bag_id, "from": str(src.truck_id), "to": str(dest.truck_id)},
    ))
    db.commit()
    return get_load_rosters(sort_date=sort_date, mine=False, caller=caller, _={}, db=db)


@router.post("/{sort_date}/trucks/{truck_id}/check-all", response_model=RostersResponse)
def check_all_totes(
    sort_date: date,
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Check off every remaining tote on one truck in a single action.

    Dispatch-only — bulk confirmation is a supervisory act; drivers check
    individually for accountability. Confirmed transfers whose destination is
    this truck complete as their totes check in.
    """
    from datetime import datetime, timezone
    from app.models.audit_log import AuditLog
    from app.models.tote_ops import ToteTransfer, ToteLoadCheck

    zones = [z for z in _active_zones(db, caller.company_id, sort_date) if z.truck_id == truck_id]
    if not zones:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active zone for that truck on this date.")

    already = {
        c.bag_id
        for c in db.query(ToteLoadCheck).filter(
            ToteLoadCheck.company_id == caller.company_id,
            ToteLoadCheck.load_date == sort_date,
        ).all()
    }
    now = datetime.now(timezone.utc)
    newly_checked: list[str] = []
    for z in zones:
        for entry in (z.tote_roster or []):
            bag = entry["bag_id"]
            if bag in already:
                continue
            db.add(ToteLoadCheck(
                id=_uuid_mod.uuid4(),
                company_id=caller.company_id,
                load_date=sort_date,
                truck_id=truck_id,
                bag_id=bag,
                checked_by=caller.id,
                checked_by_name=caller.name,
            ))
            newly_checked.append(bag)

    if newly_checked:
        for xfer in db.query(ToteTransfer).filter(
            ToteTransfer.company_id == caller.company_id,
            ToteTransfer.transfer_date == sort_date,
            ToteTransfer.status == "confirmed",
            ToteTransfer.to_truck_id == truck_id,
            ToteTransfer.bag_id.in_(newly_checked),
        ).all():
            xfer.status = "completed"
            xfer.completed_at = now

        db.flush()
        db.add(AuditLog(
            company_id=caller.company_id,
            actor_id=caller.id,
            action_type="sort.tote_check_all",
            target_table="tote_load_checks",
            target_id=zones[0].id,
            after_snapshot={"truck_id": str(truck_id), "count": len(newly_checked), "date": sort_date.isoformat()},
        ))
        db.commit()
    return get_load_rosters(sort_date=sort_date, mine=False, caller=caller, _={}, db=db)


@router.post("/transfers/{transfer_id}/undo", response_model=RostersResponse)
def undo_transfer(
    transfer_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Undo a transfer decision that hasn't physically completed.

    confirmed + rerun_diff — zone data never moved; revert to `suggested`.
    confirmed + dispatch   — zone data moved at creation; move it back and mark
                             the record `undone` (kept for audit).
    kept                   — zone data was realigned to the physical truck;
                             move it forward again and revert to `suggested`.
    completed              — cannot undo: the tote physically moved and was
                             checked in. Issue a new manual transfer instead.
    """
    from app.models.audit_log import AuditLog
    from app.models.tote_ops import ToteTransfer

    xfer = (
        db.query(ToteTransfer)
        .filter(ToteTransfer.id == transfer_id, ToteTransfer.company_id == caller.company_id)
        .first()
    )
    if xfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found.")

    if xfer.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transfer already completed — the tote was physically moved and checked in. Create a new transfer to move it again.",
        )
    if xfer.status == "suggested":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transfer has no decision to undo yet.")
    if xfer.status == "undone":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transfer is already undone.")

    if xfer.status == "confirmed" and xfer.reason == "dispatch":
        _move_bag_between_zones(db, caller.company_id, xfer.transfer_date, xfer.bag_id, xfer.from_truck_id)
        xfer.status = "undone"
    elif xfer.status == "confirmed":   # rerun_diff — zone data untouched by confirm
        xfer.status = "suggested"
        xfer.resolved_by = None
        xfer.resolved_by_name = None
        xfer.resolved_at = None
    else:                              # kept — re-apply the sort's intent
        _move_bag_between_zones(db, caller.company_id, xfer.transfer_date, xfer.bag_id, xfer.to_truck_id)
        xfer.status = "suggested"
        xfer.resolved_by = None
        xfer.resolved_by_name = None
        xfer.resolved_at = None

    db.flush()
    db.add(AuditLog(
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="sort.transfer_undo",
        target_table="tote_transfers",
        target_id=xfer.id,
        after_snapshot={"bag_id": xfer.bag_id, "new_status": xfer.status},
    ))
    db.commit()
    return get_load_rosters(sort_date=xfer.transfer_date, mine=False, caller=caller, _={}, db=db)
