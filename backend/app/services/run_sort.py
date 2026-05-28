"""run_sort — manifest sort pipeline orchestrator.

Pipeline:
    1. Load enriched packages from Redis (written by enrich_manifest Celery task)
    2. cluster_packages()  → ClusterResult   (DBSCAN geographic clustering)
    3. assign_clusters()   → AssignmentProposal  (historical + sequential + overflow)
    4. tier1_verify()      → VerificationResult  (misload detection)
    5. If clean (or force=True): persist_zones() → TruckZone rows written to DB
    6. Notify dispatch of result

The caller owns the DB session and commit. run_sort() does NOT commit — it
flushes new TruckZone rows and returns the full result so the router can decide
whether to commit (success) or rollback (error path).

Raises:
    SortError — structured error with a code the router can map to HTTP status.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

import redis as redis_lib
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.company import CompanyConfig, CompanyZone
from app.models.location_profile import LocationProfile
from app.models.location_profile_library import LocationProfileLibrary
from app.models.truck import Truck
from app.models.truck_zone import TruckZone
from app.services.assign_clusters import assign_clusters, AssignmentProposal
from app.services.cluster_packages import cluster_packages, ClusterResult
from app.services.persist_zones import persist_zones
from app.services.tier1_verify import tier1_verify, VerificationResult

logger = logging.getLogger(__name__)

# Platform defaults for DBSCAN — used when CompanyConfig fields are null
_DEFAULT_EPS         = 0.015
_DEFAULT_MIN_SAMPLES = 30


# ── error type ────────────────────────────────────────────────────────────────

class SortError(Exception):
    """Raised by run_sort() for known failure modes.

    code values (used by router to map HTTP status):
        "no_manifest"      — Redis key missing or expired
        "no_trucks"        — company has no active trucks
        "no_packages"      — manifest is present but empty
        "tier1_failed"     — misaligned totes detected; force=False
        "config_missing"   — CompanyConfig row absent
    """
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code   = code
        self.detail = detail


# ── result type ───────────────────────────────────────────────────────────────

@dataclass
class SortResult:
    cluster_result:   ClusterResult
    proposal:         AssignmentProposal
    verification:     VerificationResult
    zones_persisted:  list[TruckZone]      # empty if tier1 failed and force=False
    sort_date:        date
    package_count:    int
    outlier_count:    int
    cluster_count:    int
    tier1_passed:     bool
    was_forced:       bool                 # True if caller passed force=True despite failures


# ── Redis helper ──────────────────────────────────────────────────────────────

def _load_manifest_from_redis(company_id: str, sort_date: str) -> list[dict]:
    r = redis_lib.from_url(settings.redis_url, decode_responses=True)
    key = f"manifest:{company_id}:{sort_date}"
    raw = r.get(key)
    if raw is None:
        raise SortError(
            "no_manifest",
            f"No enriched manifest found for {sort_date}. "
            "Upload and enrich the manifest before running sort.",
        )
    return json.loads(raw)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_config(db: Session, company_id: UUID) -> CompanyConfig:
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if cfg is None:
        raise SortError("config_missing", "Company configuration not found.")
    return cfg


def _get_active_trucks(db: Session, company_id: UUID) -> list[dict]:
    trucks = (
        db.query(Truck)
        .filter(Truck.company_id == company_id, Truck.is_active.is_(True))
        .order_by(Truck.name)
        .all()
    )
    if not trucks:
        raise SortError("no_trucks", "No active trucks found. Add trucks before running sort.")
    return [{"id": t.id, "name": t.name} for t in trucks]


def _get_recent_zones(db: Session, company_id: UUID) -> list[dict]:
    """Return the most recent active zone per truck as centroid dicts."""
    # Subquery: latest zone_date per truck_id for this company
    from sqlalchemy import func as sqlfunc
    sub = (
        db.query(
            TruckZone.truck_id,
            sqlfunc.max(TruckZone.zone_date).label("max_date"),
        )
        .filter(TruckZone.company_id == company_id, TruckZone.is_active.is_(True))
        .group_by(TruckZone.truck_id)
        .subquery()
    )
    zones = (
        db.query(TruckZone)
        .join(sub, (TruckZone.truck_id == sub.c.truck_id) & (TruckZone.zone_date == sub.c.max_date))
        .filter(TruckZone.company_id == company_id)
        .all()
    )
    result = []
    for z in zones:
        poly = z.truck_polygon or []
        if not poly:
            continue
        lats = [v["lat"] for v in poly]
        lngs = [v["lng"] for v in poly]
        centroid = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
        result.append({"truck_id": z.truck_id, "centroid": centroid})
    return result


def _get_company_boundary(db: Session, company_id: UUID) -> list[dict]:
    """Return the top-level company zone polygon, or [] if none configured."""
    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .order_by(CompanyZone.created_at.desc())
        .first()
    )
    if zone is None or not zone.bounds:
        return []
    coords = zone.bounds.get("coordinates", [[]])[0]
    return [{"lat": c[1], "lng": c[0]} for c in coords]


def _get_location_profiles(db: Session, company_id: UUID) -> list[dict]:
    """Return all locked company profiles + active library records.

    Company record takes precedence: if the same block_key+workload_class
    exists in both, the company row wins. The router/service layer always
    sees a flat list; shadowing is resolved here by inserting company records
    last so they overwrite library entries in the block_key → workload_class
    dict built by assign_clusters._score_cluster.
    """
    # Global library (cold-start data — all active records)
    library = (
        db.query(LocationProfileLibrary)
        .filter(LocationProfileLibrary.library_status == "active")
        .all()
    )
    # Company-scoped (locked only — pending/verified don't influence routing yet)
    company = (
        db.query(LocationProfile)
        .filter(
            LocationProfile.company_id == company_id,
            LocationProfile.building_type_status == "locked",
        )
        .all()
    )
    profiles = [{"block_key": r.block_key, "workload_class": r.workload_class} for r in library]
    profiles += [{"block_key": r.block_key, "workload_class": r.workload_class} for r in company]
    return profiles


# ── main orchestrator ─────────────────────────────────────────────────────────

def run_sort(
    company_id: UUID,
    sort_date: date,
    totes: list[dict],       # [{"tote_id": str, "truck_id": UUID, "packages": [...]}]
    created_by: UUID,
    created_by_name: str,
    db: Session,
    force: bool = False,     # persist zones even if tier1 has non-clean totes
) -> SortResult:
    """Run the full manifest sort pipeline for one company and date.

    Args:
        company_id:       Tenant scope.
        sort_date:        The sort day.
        totes:            Tote/package data for tier1 verification. Each tote is a dict
                          with keys: tote_id (str), truck_id (UUID), packages (list of
                          dicts with tba/lat/lng).
        created_by:       Employee ID of the dispatch user triggering the sort.
        created_by_name:  Display name for audit fields on TruckZone rows.
        db:               SQLAlchemy session — caller owns commit/rollback.
        force:            If True, persist zones even when tier1 flags misaligned totes.
                          Dispatch can override after reviewing the flagged totes.

    Returns:
        SortResult — full pipeline output.

    Raises:
        SortError — on known failure modes (see SortError.code values).
    """
    cid_str = str(company_id)
    date_str = sort_date.isoformat()

    # 1. Load enriched packages from Redis
    packages = _load_manifest_from_redis(cid_str, date_str)
    if not packages:
        raise SortError("no_packages", f"Manifest for {date_str} is empty.")

    # 2. Load DB dependencies
    cfg        = _get_config(db, company_id)
    trucks     = _get_active_trucks(db, company_id)
    recent_zones = _get_recent_zones(db, company_id)
    boundary   = _get_company_boundary(db, company_id)
    profiles   = _get_location_profiles(db, company_id)

    eps         = cfg.tier1_dbscan_eps         or _DEFAULT_EPS
    min_samples = cfg.tier1_dbscan_min_samples or _DEFAULT_MIN_SAMPLES

    # 3. Cluster
    cluster_result = cluster_packages(packages, eps=eps, min_samples=min_samples)

    # 4. Assign clusters to trucks
    proposal = assign_clusters(
        result=cluster_result,
        trucks=trucks,
        recent_zones=recent_zones,
        company_boundary=boundary,
        location_profiles=profiles,
    )

    # 5. Tier-1 tote verification
    verification = tier1_verify(proposal=proposal, totes=totes, cfg=cfg)

    tier1_passed = verification.all_clean
    zones_persisted: list[TruckZone] = []

    # 6. Persist zones (only if clean, or force override)
    if tier1_passed or force:
        zones_persisted = persist_zones(
            proposal=proposal,
            zone_date=sort_date,
            company_id=company_id,
            created_by=created_by,
            created_by_name=created_by_name,
            db=db,
        )

    if not tier1_passed and not force:
        raise SortError(
            "tier1_failed",
            f"Tier-1 verification flagged {len(verification.flagged)} tote(s). "
            "Review flagged totes and resubmit with force=true to override.",
        )

    logger.info(
        "run_sort complete",
        extra={
            "company_id":    cid_str,
            "sort_date":     date_str,
            "packages":      len(packages),
            "clusters":      len(cluster_result.clusters),
            "outliers":      len(cluster_result.outliers),
            "tier1_passed":  tier1_passed,
            "forced":        force and not tier1_passed,
            "zones":         len(zones_persisted),
        },
    )

    return SortResult(
        cluster_result  = cluster_result,
        proposal        = proposal,
        verification    = verification,
        zones_persisted = zones_persisted,
        sort_date       = sort_date,
        package_count   = len(packages),
        outlier_count   = len(cluster_result.outliers),
        cluster_count   = len(cluster_result.clusters),
        tier1_passed    = tier1_passed,
        was_forced      = force and not tier1_passed,
    )
