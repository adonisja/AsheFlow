"""Location profile library router — super admin management of the global library.

This is the Tier A (platform-wide) layer of location intelligence.
All tenants can read; only super admins can write.

Endpoints:
    GET    /location-profile-library/               list all active library records (any authed user)
    GET    /location-profile-library/{id}           single record (any authed user)
    GET    /location-profile-library/nominations    list pending nominations (super admin)
    POST   /location-profile-library/nominations/{company_id}/{profile_id}/decide
                                                    approve or reject a nomination (super admin)
    PATCH  /location-profile-library/{id}/status   resolve conflict or deprecate (super admin)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, get_super_admin, Pagination
from app.database import get_db
from app.models.employee import Employee
from app.models.location_profile import LocationProfile
from app.models.location_profile_library import LocationProfileLibrary
from app.schemas.location_profile import (
    LibraryStatusPatch,
    LocationProfileLibraryResponse,
    LocationProfileResponse,
    NominationDecision,
    derive_workload_class,
)

router = APIRouter(prefix="/location-profile-library", tags=["location-profile-library"])

allow_read = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


# ── read endpoints (any authenticated employee) ───────────────────────────────

@router.get("/", response_model=list[LocationProfileLibraryResponse])
def list_library(
    block_key:     str | None = Query(None),
    building_type: str | None = Query(None),
    library_status: str | None = Query(None),
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_read),
    db: Session = Depends(get_db),
):
    """List global library records. Defaults to active records only."""
    q = db.query(LocationProfileLibrary)
    if library_status:
        q = q.filter(LocationProfileLibrary.library_status == library_status)
    else:
        q = q.filter(LocationProfileLibrary.library_status == "active")
    if block_key:
        q = q.filter(LocationProfileLibrary.block_key == block_key)
    if building_type:
        q = q.filter(LocationProfileLibrary.building_type == building_type)
    q = q.order_by(LocationProfileLibrary.block_key, LocationProfileLibrary.building_type)
    rows = pg.apply(q).all()
    return [LocationProfileLibraryResponse.from_orm_with_protocol(r) for r in rows]


@router.get("/nominations", response_model=list[LocationProfileResponse])
def list_nominations(
    pg: Pagination = Depends(),
    super_admin: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """List all company profiles nominated for library promotion (super admin only)."""
    q = (
        db.query(LocationProfile)
        .filter(LocationProfile.nomination_status == "nominated")
        .order_by(LocationProfile.updated_at.desc())
    )
    rows = pg.apply(q).all()
    return [LocationProfileResponse.from_orm_with_protocol(r) for r in rows]


@router.get("/{library_id}", response_model=LocationProfileLibraryResponse)
def get_library_record(
    library_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_read),
    db: Session = Depends(get_db),
):
    record = db.query(LocationProfileLibrary).filter(LocationProfileLibrary.id == library_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library record not found.")
    return LocationProfileLibraryResponse.from_orm_with_protocol(record)


# ── super admin write endpoints ───────────────────────────────────────────────

@router.post(
    "/nominations/{company_id}/{profile_id}/decide",
    response_model=LocationProfileResponse,
)
def decide_nomination(
    company_id: UUID,
    profile_id: UUID,
    body: NominationDecision,
    super_admin: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Approve or reject a company profile's nomination for the global library.

    Approved: creates or updates a library record; sets nomination_status = "promoted".
    Rejected: sets nomination_status = "rejected"; record stays in company profiles.
    """
    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="decision must be 'approved' or 'rejected'.",
        )

    profile = (
        db.query(LocationProfile)
        .filter(
            LocationProfile.id == profile_id,
            LocationProfile.company_id == company_id,
            LocationProfile.nomination_status == "nominated",
        )
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nominated profile not found.",
        )

    now = datetime.now(timezone.utc)
    admin_id   = UUID(super_admin["id"])
    admin_name = super_admin.get("email", "super_admin")

    if body.decision == "rejected":
        profile.nomination_status = "rejected"
        profile.updated_at = now
        db.commit()
        db.refresh(profile)
        return LocationProfileResponse.from_orm_with_protocol(profile)

    # Approved — upsert library record
    lib = (
        db.query(LocationProfileLibrary)
        .filter(
            LocationProfileLibrary.block_key == profile.block_key,
            LocationProfileLibrary.building_type == profile.building_type,
        )
        .first()
    )

    if lib:
        # Update existing — carry over note if newly verified
        if profile.operational_note and profile.note_verified:
            lib.operational_note  = profile.operational_note
            lib.note_verified     = True
            lib.note_verified_by  = admin_id
            lib.note_verified_by_name = admin_name
            lib.note_verified_at  = now
        lib.agreement_source_count += 1
        lib.library_status  = "active"
        lib.updated_by      = admin_id
        lib.updated_by_name = admin_name
        lib.updated_at      = now
        # Track which companies contributed
        sources = list(lib.promoted_from_company_ids or [])
        if company_id not in sources:
            sources.append(company_id)
        lib.promoted_from_company_ids = sources
    else:
        lib = LocationProfileLibrary(
            block_key               = profile.block_key,
            building_type           = profile.building_type,
            workload_class          = profile.workload_class,
            library_status          = "active",
            agreement_source_count  = 1,
            operational_note        = profile.operational_note if profile.note_verified else None,
            note_verified           = profile.note_verified,
            note_verified_by        = admin_id if profile.note_verified else None,
            note_verified_by_name   = admin_name if profile.note_verified else None,
            note_verified_at        = now if profile.note_verified else None,
            promoted_from_company_ids = [company_id],
            promoted_at             = now,
            promoted_by             = admin_id,
            promoted_by_name        = admin_name,
            created_by              = admin_id,
            created_by_name         = admin_name,
            updated_by              = admin_id,
            updated_by_name         = admin_name,
            updated_at              = now,
        )
        db.add(lib)

    profile.nomination_status = "promoted"
    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.patch("/{library_id}/status", response_model=LocationProfileLibraryResponse)
def patch_library_status(
    library_id: UUID,
    body: LibraryStatusPatch,
    super_admin: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Resolve a conflict or deprecate a library record (super admin only)."""
    if body.library_status not in {"active", "deprecated"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="library_status must be 'active' or 'deprecated'.",
        )

    record = db.query(LocationProfileLibrary).filter(LocationProfileLibrary.id == library_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library record not found.")

    now = datetime.now(timezone.utc)
    admin_id   = UUID(super_admin["id"])
    admin_name = super_admin.get("email", "super_admin")

    record.library_status = body.library_status
    if body.operational_note is not None:
        record.operational_note = body.operational_note
    record.last_conflict_at = None if body.library_status == "active" else record.last_conflict_at
    record.updated_by       = admin_id
    record.updated_by_name  = admin_name
    record.updated_at       = now
    db.commit()
    db.refresh(record)
    return LocationProfileLibraryResponse.from_orm_with_protocol(record)
