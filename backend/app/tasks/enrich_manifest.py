"""Celery task: async GeoClient address enrichment for uploaded manifests.

Flow:
  1. Dispatch uploads manifest → FileManifestIngestor produces RawPackage list
  2. This task is dispatched immediately with the raw packages
  3. For each package: GeoClient API → normalised address → derive_block_key → block_key
  4. Enriched packages cached in Redis under key manifest:{company_id}:{date}  (TTL 24h)
  5. Failed packages collected; dispatch notified with TBA + raw address + reason
  6. On completion: dispatch notified "manifest sort-ready"

GeoClient: NYC Department of City Planning free API (v2).
Auth: Ocp-Apim-Subscription-Key HTTP header — get key from api-portal.nyc.gov ("Geoclient - v2" product).
Endpoint: GET /geoclient/v2/address.json?houseNumber=411&street=W+36+St&borough=manhattan
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import requests
import redis as redis_lib

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.notification import Notification
from app.services.derive_block_key import derive_block_key, ParsedBlock

logger = logging.getLogger(__name__)

_GEOCLIENT_BASE = "https://api.nyc.gov/geoclient/v2"
_REDIS_TTL_SECONDS = 86_400   # 24 hours
_ENRICHING_KEY_TTL = 300      # 5 min — progress key; deleted on completion


# ── GeoClient helpers ─────────────────────────────────────────────────────────

def _parse_house_and_street(address: str) -> tuple[str, str] | None:
    """Split '411 W 36 St' into ('411', 'W 36 St').  Returns None if unparseable."""
    parts = address.strip().split(None, 1)
    if len(parts) != 2:
        return None
    house, street = parts
    if not house.rstrip("-").replace("/", "").isdigit():
        return None
    return house, street


@dataclass
class GeoClientResult:
    normalised_address: str
    lat: float | None
    lng: float | None
    first_cross_street: str | None
    second_cross_street: str | None


def _geoclient_normalise(address: str, borough: str = "manhattan") -> GeoClientResult | None:
    """Call GeoClient v2 address endpoint; return enriched location data or None.

    v2 auth: Ocp-Apim-Subscription-Key HTTP header (not query param; app_id/app_key are v1 only).
    Returns None when key is unset — caller falls back to raw address parsing.
    """
    if not settings.geoclient_app_key:
        return None

    parsed = _parse_house_and_street(address)
    if parsed is None:
        return None
    house, street = parsed

    try:
        resp = requests.get(
            f"{_GEOCLIENT_BASE}/address.json",
            params={
                "houseNumber": house,
                "street":      street,
                "borough":     borough,
            },
            headers={
                "Ocp-Apim-Subscription-Key": settings.geoclient_app_key,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})

        first_street = addr.get("firstStreetNameNormalized") or addr.get("firstStreetName")
        if not first_street:
            return None

        lat_raw = addr.get("latitude")
        lng_raw = addr.get("longitude")

        try:
            lat = float(lat_raw) if lat_raw is not None else None
            lng = float(lng_raw) if lng_raw is not None else None
        except (TypeError, ValueError):
            lat, lng = None, None

        return GeoClientResult(
            normalised_address=f"{house} {first_street}",
            lat=lat,
            lng=lng,
            # GeoClient v2 uses lowCrossStreetName1/highCrossStreetName1 for
            # the bounding cross streets. The older firstCrossStreetName* fields
            # are absent from v2 responses but kept as fallback.
            first_cross_street=(
                addr.get("lowCrossStreetName1")
                or addr.get("firstCrossStreetNameNormalized")
                or addr.get("firstCrossStreetName")
                or None
            ),
            second_cross_street=(
                addr.get("highCrossStreetName1")
                or addr.get("secondCrossStreetNameNormalized")
                or addr.get("secondCrossStreetName")
                or None
            ),
        )
    except Exception:
        pass
    return None


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _redis_client() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _manifest_key(company_id: str, sort_date: str) -> str:
    return f"manifest:{company_id}:{sort_date}"


def _progress_key(company_id: str, sort_date: str) -> str:
    return f"manifest_progress:{company_id}:{sort_date}"


# ── notification helper ───────────────────────────────────────────────────────

def _notify_dispatch(company_id: UUID, message: str, db) -> None:
    employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(["dispatch", "management", "admin"]),
            Employee.is_active.is_(True),
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    for emp in employees:
        db.add(Notification(
            company_id=company_id,
            employee_id=emp.id,
            type="manifest_enrichment",
            message=message,
            created_at=now,
        ))
    db.commit()


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.enrich_manifest.enrich_manifest_packages",
    bind=True,
    max_retries=0,  # outer task doesn't retry; per-package retries handled inside
)
def enrich_manifest_packages(
    self,
    company_id: str,
    sort_date: str,          # ISO date string "YYYY-MM-DD"
    packages: list[dict],    # RawPackage dicts: {tba, lat, lng, address, ...}
    borough: str = "manhattan",
) -> dict:
    """Enrich a manifest's packages with block_key via GeoClient.

    Stores enriched packages in Redis. Notifies dispatch on completion and on
    any failures. Safe to re-run: Redis key is overwritten.

    On unhandled exception, writes a manifest_failed:{company_id}:{date} key
    to Redis (TTL 24h) so the status endpoint can return "failed" instead of
    leaving dispatch with a silent "not_found" response.
    """
    _failed_key = f"manifest_failed:{company_id}:{sort_date}"
    r = _redis_client()

    # Clear the worker_unreachable sentinel written at upload time — the task
    # was received, so the worker is alive. Any real failure will re-set this key.
    current_failed = r.get(_failed_key)
    if current_failed == "worker_unreachable":
        r.delete(_failed_key)

    try:
        return _run_enrichment(self, company_id, sort_date, packages, borough, r, _failed_key)
    except Exception as exc:
        logger.error(
            "enrich_manifest_packages unhandled exception: %s",
            type(exc).__name__,
            extra={"company_id": company_id, "sort_date": sort_date},
        )
        r.setex(_failed_key, _REDIS_TTL_SECONDS, "internal_error")
        raise


# GeoClient v2 (api.nyc.gov) rate limit: 5,000 req/min per subscription key.
# At 10 workers × ~300ms avg latency ≈ 2,000 req/min — safely under the cap.
# Raising above 15 risks 429s which count as geoclient_error and inflate failed_count.
_GEOCLIENT_WORKERS = 10


def _enrich_one(pkg: dict, borough: str) -> dict:
    """Enrich a single package: GeoClient lookup + block_key derivation.

    Returns a result dict with keys: enriched_pkg, failed_entry (or None), ov_entry (or None).
    Pure function — no shared state, safe to call from a thread pool.
    """
    address = pkg.get("address") or ""
    tba = pkg.get("tba", "unknown")
    tag = pkg.get("tag_number")
    package_type = pkg.get("package_type")
    bag_id = pkg.get("bag_id")
    amazon_lat = pkg.get("lat")
    amazon_lng = pkg.get("lng")

    geo: GeoClientResult | None = None
    block_key: str | None = None
    failure_reason: str | None = None

    ov_entry = None
    if tag:
        ov_entry = {
            "tba":          tba,
            "bag_id":       bag_id,
            "tag_number":   tag.strip(),
            "package_type": package_type,
        }

    if address:
        for attempt in range(3):
            try:
                geo = _geoclient_normalise(address, borough=borough)
                break
            except Exception as geo_exc:
                logger.warning(
                    "geoclient_retry",
                    extra={
                        "attempt":    attempt + 1,
                        "tba":        tba,
                        "error_type": type(geo_exc).__name__,
                        "error":      str(geo_exc)[:120],
                    },
                )
                if attempt == 2:
                    failure_reason = "geoclient_error"

        if geo is None and not failure_reason:
            failure_reason = "geoclient_no_match"

        source = geo.normalised_address if geo else address
        bk_result = derive_block_key(source, tba=tba)
        if isinstance(bk_result, ParsedBlock):
            block_key = bk_result.block_key
        elif failure_reason is None:
            failure_reason = bk_result.reason
    else:
        failure_reason = "missing_address"

    if failure_reason:
        logger.debug("package_enrich_failed", extra={"tba": tba, "reason": failure_reason})

    final_lat = geo.lat if geo and geo.lat is not None else amazon_lat
    final_lng = geo.lng if geo and geo.lng is not None else amazon_lng

    enriched_pkg = {
        "tba":                tba,
        "bag_id":             bag_id,
        "tag_number":         tag,
        "package_type":       package_type,
        "lat":                final_lat,
        "lng":                final_lng,
        "block_key":          block_key,
        "raw_address":        address,           # original manifest address — always preserved
        "normalised_address": geo.normalised_address if geo else None,
        "first_cross_street": geo.first_cross_street if geo else None,
        "second_cross_street":geo.second_cross_street if geo else None,
        "geocode_reason":     failure_reason,    # None for success; error code for failures
    }

    failed_entry = {"tba": tba, "raw_address": address, "reason": failure_reason} if failure_reason else None

    return {"enriched_pkg": enriched_pkg, "failed_entry": failed_entry, "ov_entry": ov_entry}


def _run_enrichment(self, company_id, sort_date, packages, borough, r, _failed_key):
    total_packages = len(packages)
    t_start = time.monotonic()
    log_interval = max(500, total_packages // 10)

    logger.info(
        "enrich_manifest_packages started",
        extra={
            "company_id": company_id,
            "sort_date":  sort_date,
            "total":      total_packages,
            "borough":    borough,
            "geoclient":  bool(settings.geoclient_app_key),
            "workers":    _GEOCLIENT_WORKERS,
        },
    )

    # Submit all packages to the thread pool; collect results in original order.
    # ThreadPoolExecutor is safe here: _enrich_one has no shared mutable state.
    results: list[dict] = [None] * total_packages  # type: ignore[list-item]
    prog_key = _progress_key(company_id, sort_date)
    with ThreadPoolExecutor(max_workers=_GEOCLIENT_WORKERS) as pool:
        future_to_idx = {pool.submit(_enrich_one, pkg, borough): i for i, pkg in enumerate(packages)}
        completed = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
            completed += 1
            if completed % log_interval == 0 or completed == total_packages:
                elapsed = time.monotonic() - t_start
                failed_so_far = sum(1 for r2 in results[:completed] if r2 and r2["failed_entry"])
                r.setex(
                    prog_key,
                    _ENRICHING_KEY_TTL,
                    json.dumps({"processed": completed, "total": total_packages, "elapsed_s": round(elapsed, 1)}),
                )
                logger.info(
                    "enrich_manifest_progress",
                    extra={
                        "company_id":    company_id,
                        "sort_date":     sort_date,
                        "processed":     completed,
                        "total":         total_packages,
                        "failed_so_far": failed_so_far,
                        "elapsed_s":     round(elapsed, 1),
                    },
                )

    # Unpack results (order preserved — results list was pre-sized)
    enriched:    list[dict] = [res["enriched_pkg"] for res in results]
    failed:      list[dict] = [res["failed_entry"] for res in results if res["failed_entry"]]
    ov_packages: list[dict] = [res["ov_entry"]     for res in results if res["ov_entry"]]

    total = total_packages

    # Block sort if too many packages failed enrichment.
    if total >= 10 and failed:
        fail_pct = len(failed) / total
        threshold = settings.geoclient_failure_threshold
        if fail_pct > threshold:
            reason = (
                f"enrichment_threshold_exceeded:{len(failed)}/{total}_failed"
                + ("_no_api_key" if not settings.geoclient_app_key else "")
            )
            r.setex(_failed_key, _REDIS_TTL_SECONDS, reason)
            r.delete(prog_key)
            # Delete the enriching sentinel so the status endpoint returns
            # "failed" immediately rather than staying stuck on "enriching".
            r.delete(f"manifest_enriching:{company_id}:{sort_date}")
            db = SessionLocal()
            try:
                cid = UUID(company_id)
                key_hint = " GeoClient API key is not configured." if not settings.geoclient_app_key else ""
                _notify_dispatch(
                    cid,
                    f"Manifest enrichment failed for {sort_date}: "
                    f"{len(failed)}/{total} packages could not be geocoded ({fail_pct:.0%}).{key_hint} "
                    f"Sort is blocked — fix the issue and re-upload.",
                    db,
                )
            finally:
                db.close()
            logger.error(
                "enrich_manifest_packages: failure threshold exceeded",
                extra={"company_id": company_id, "date": sort_date,
                       "failed": len(failed), "total": total, "pct": fail_pct},
            )
            return {"total": total, "enriched": total - len(failed), "failed": len(failed), "threshold_exceeded": True}

    # Cache enriched packages in Redis
    key = _manifest_key(company_id, sort_date)
    r.setex(key, _REDIS_TTL_SECONDS, json.dumps(enriched))

    if ov_packages:
        ov_key = f"manifest_ov_zones:{company_id}:{sort_date}"
        r.setex(ov_key, _REDIS_TTL_SECONDS, json.dumps(ov_packages))

    r.delete(_failed_key)
    r.delete(prog_key)

    db = SessionLocal()
    try:
        cid = UUID(company_id)

        if failed:
            lines = "\n".join(
                f"• {f['tba']} — {f['raw_address'] or 'no address'} ({f['reason']})"
                for f in failed[:10]
            )
            suffix = f"\n…and {len(failed) - 10} more." if len(failed) > 10 else ""
            _notify_dispatch(
                cid,
                f"{len(failed)} package(s) could not be enriched for {sort_date}. "
                f"Review before sort:\n{lines}{suffix}",
                db,
            )

        ok = total - len(failed)
        _notify_dispatch(
            cid,
            f"Manifest enrichment complete for {sort_date}: "
            f"{ok}/{total} packages ready. "
            + (f"{len(failed)} flagged — check notifications." if failed else "All packages enriched."),
            db,
        )
    finally:
        db.close()

    elapsed_total = round(time.monotonic() - t_start, 1)
    logger.info(
        "enrich_manifest_packages complete",
        extra={
            "company_id": company_id,
            "date":       sort_date,
            "total":      total_packages,
            "enriched":   total_packages - len(failed),
            "failed":     len(failed),
            "elapsed_s":  elapsed_total,
        },
    )

    return {"total": total_packages, "enriched": total_packages - len(failed), "failed": len(failed)}
