"""Sort router — manifest sort pipeline endpoints.

POST /sort/run       — run the full sort pipeline for a given date
GET  /sort/{date}    — fetch existing zone results for a date (for re-display without re-running)
"""
from __future__ import annotations

from datetime import date
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.employee import Employee
from app.models.truck_zone import TruckZone
from app.services.run_sort import run_sort, SortError

router = APIRouter(prefix="/sort", tags=["sort"])

allow_sort = RoleChecker(["dispatch", "management", "admin"])


# ── request / response schemas ────────────────────────────────────────────────

class TotePackageIn(BaseModel):
    tba: str
    lat: float
    lng: float


class ToteIn(BaseModel):
    tote_id: str
    truck_id: UUID
    packages: list[TotePackageIn]


class SortRunRequest(BaseModel):
    sort_date: date
    totes: list[ToteIn]
    force: bool = False


class ToteResultOut(BaseModel):
    tote_id: str
    truck_id: UUID
    classification: str
    total_packages: int
    outside_packages: int
    outside_pct: float
    outside_tbas: list[str]
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
    flagged_totes: list[ToteResultOut]


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


# ── endpoints ─────────────────────────────────────────────────────────────────

_SORT_ERROR_STATUS = {
    "no_manifest": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "no_trucks":   status.HTTP_422_UNPROCESSABLE_ENTITY,
    "no_packages": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "tier1_failed": status.HTTP_409_CONFLICT,
    "config_missing": status.HTTP_503_SERVICE_UNAVAILABLE,
}


@router.post("/run", response_model=SortRunResponse, status_code=status.HTTP_200_OK)
def run_sort_endpoint(
    body: SortRunRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Run the manifest sort pipeline for the given date.

    - Loads enriched packages from Redis (must have been enriched first via manifest upload)
    - Clusters packages with DBSCAN → assigns clusters to trucks → tier-1 tote verification
    - If tier-1 passes (or force=True), writes TruckZone rows and commits
    - Returns the full assignment breakdown and any flagged totes

    409 Conflict is returned when tier-1 flags totes and force=False.
    The client should display the flagged totes and let dispatch confirm before
    resubmitting with force=True.
    """
    totes_raw = [t.model_dump() for t in body.totes]

    try:
        result = run_sort(
            company_id      = caller.company_id,
            sort_date       = body.sort_date,
            totes           = totes_raw,
            created_by      = caller.id,
            created_by_name = caller.name,
            db              = db,
            force           = body.force,
        )
    except SortError as exc:
        http_status = _SORT_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=http_status, detail=exc.detail)

    db.commit()

    assignments_out = [
        ClusterAssignmentOut(
            truck_id      = a.truck_id,
            truck_name    = a.truck_name,
            match_type    = a.match_type,
            workload_score = a.workload_score,
            is_overflow   = a.is_overflow,
            package_count = len(a.cluster.packages),
        )
        for a in result.proposal.assignments
    ]

    flagged_out = [
        ToteResultOut(
            tote_id           = t.tote_id,
            truck_id          = t.truck_id,
            classification    = t.classification,
            total_packages    = t.total_packages,
            outside_packages  = t.outside_packages,
            outside_pct       = t.outside_pct,
            outside_tbas      = t.outside_tbas,
            suggested_truck_id = t.suggested_truck_id,
            unresolvable      = t.unresolvable,
        )
        for t in result.verification.flagged
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
        flagged_totes = flagged_out,
    )


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
