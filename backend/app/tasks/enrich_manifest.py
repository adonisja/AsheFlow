"""Celery task: async GeoClient address enrichment for uploaded manifests.

Flow:
  1. Dispatch uploads manifest → FileManifestIngestor produces RawPackage list
  2. This task is dispatched immediately with the raw packages
  3. For each package: GeoClient API → normalised address → derive_block_key → block_key
  4. Enriched packages cached in Redis under key manifest:{company_id}:{date}  (TTL 24h)
  5. Failed packages collected; dispatch notified with TBA + raw address + reason
  6. On completion: dispatch notified "manifest sort-ready"

GeoClient: NYC Department of City Planning free API.
Docs: https://api.nyc.gov/space/1/services/nyc-geo-client/docs
Endpoint: GET /geoclient/v2/address.json?houseNumber=411&street=W+36+St&borough=manhattan
"""

import json
import logging
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

_GEOCLIENT_BASE = "https://api.nyc.gov/space/1/services/nyc-geo-client/api/geoclient/v2"
_REDIS_TTL_SECONDS = 86_400  # 24 hours


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


def _geoclient_normalise(address: str, borough: str = "manhattan") -> str | None:
    """Call GeoClient address endpoint; return normalised street string or None."""
    if not settings.geoclient_app_id or not settings.geoclient_app_key:
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
                "street": street,
                "borough": borough,
                "app_id": settings.geoclient_app_id,
                "app_key": settings.geoclient_app_key,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        first_street = addr.get("firstStreetNameNormalized") or addr.get("firstStreetName")
        if first_street:
            return f"{house} {first_street}"
    except Exception:
        pass
    return None


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _redis_client() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _manifest_key(company_id: str, sort_date: str) -> str:
    return f"manifest:{company_id}:{sort_date}"


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

    try:
        return _run_enrichment(self, company_id, sort_date, packages, borough, r, _failed_key)
    except Exception as exc:
        logger.error(
            "enrich_manifest_packages unhandled exception: %s",
            type(exc).__name__,
            extra={"company_id": company_id, "sort_date": sort_date},
        )
        r.setex(_failed_key, _REDIS_TTL_SECONDS, type(exc).__name__)
        raise


def _run_enrichment(self, company_id, sort_date, packages, borough, r, _failed_key):
    enriched: list[dict] = []
    failed: list[dict] = []

    for pkg in packages:
        address = pkg.get("address") or ""
        tba = pkg.get("tba", "unknown")

        normalised = None
        block_key = None
        failure_reason = None

        if address:
            # Attempt GeoClient normalisation (3 retries with backoff)
            for attempt in range(3):
                try:
                    normalised = _geoclient_normalise(address, borough=borough)
                    break
                except Exception:
                    if attempt == 2:
                        failure_reason = "geoclient_error"

            if normalised is None and not failure_reason:
                failure_reason = "geoclient_no_match"

            # derive_block_key on normalised address, fall back to raw address
            source = normalised or address
            result = derive_block_key(source, tba=tba)
            if isinstance(result, ParsedBlock):
                block_key = result.block_key
            else:
                if failure_reason is None:
                    failure_reason = result.reason
        else:
            failure_reason = "missing_address"

        enriched_pkg = {**pkg, "block_key": block_key, "normalised_address": normalised}
        enriched.append(enriched_pkg)

        if failure_reason:
            failed.append({
                "tba": tba,
                "raw_address": address,
                "reason": failure_reason,
            })

    # Cache enriched packages in Redis (r was passed in from caller)
    key = _manifest_key(company_id, sort_date)
    r.setex(key, _REDIS_TTL_SECONDS, json.dumps(enriched))
    # Clear any prior failure key now that enrichment succeeded
    r.delete(_failed_key)

    # Notify dispatch
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

        total = len(packages)
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

    logger.info(
        "enrich_manifest_packages complete",
        extra={"company_id": company_id, "date": sort_date, "total": len(packages), "failed": len(failed)},
    )

    return {"total": len(packages), "enriched": len(packages) - len(failed), "failed": len(failed)}
