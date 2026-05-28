"""Location profiles router — company-scoped building intelligence records.

Endpoints:
    POST   /location-profiles/                      submit a new profile (walker/captain)
    GET    /location-profiles/                      list company profiles (dispatch+)
    GET    /location-profiles/{id}                  single profile (dispatch+)
    POST   /location-profiles/{id}/verify           captain verifies building_type
    PATCH  /location-profiles/{id}/note             captain sets structured operational_note
    POST   /location-profiles/{id}/verify-note      captain verifies the operational_note
    DELETE /location-profiles/{id}                  management+ hard-delete (rare)

Nomination and promotion are handled by the super-admin library router — company
employees have no write access to location_profile_library.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.database import get_db
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.location_profile import LocationProfile
from app.schemas.location_profile import (
    LocationProfileCreate,
    LocationProfileNotePatch,
    LocationProfileResponse,
    LocationProfileVerify,
    derive_workload_class,
    BUILDING_TYPES,
)

router = APIRouter(prefix="/location-profiles", tags=["location-profiles"])

allow_read   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_submit = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_verify = RoleChecker(["dispatch", "management", "admin"])
allow_delete = RoleChecker(["management", "admin"])

_LOCK_THRESHOLD_DEFAULT = 3


def _get_lock_threshold(db: Session, company_id: UUID) -> int:
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if cfg and cfg.location_profile_lock_threshold is not None:
        return cfg.location_profile_lock_threshold
    return _LOCK_THRESHOLD_DEFAULT


def _auto_nominate_if_eligible(profile: LocationProfile) -> None:
    """Set nomination_status to 'nominated' when building_type_status reaches 'locked'."""
    if profile.building_type_status == "locked" and profile.nomination_status is None:
        profile.nomination_status = "nominated"


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=LocationProfileResponse, status_code=status.HTTP_201_CREATED)
def submit_profile(
    body: LocationProfileCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_submit),
    db: Session = Depends(get_db),
):
    """Submit a new building profile or append raw notes if one already exists.

    If a record already exists for (company_id, block_key, building_type) and
    is not yet locked, the raw_notes are appended and the record is returned.
    If locked, a 409 is returned — a locked record can only be changed through
    the verify endpoint (conflict flow).
    """
    if body.building_type not in BUILDING_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid building_type: {body.building_type!r}. "
                   f"Must be one of: {', '.join(sorted(BUILDING_TYPES))}.",
        )

    existing = (
        db.query(LocationProfile)
        .filter(
            LocationProfile.company_id == caller.company_id,
            LocationProfile.block_key == body.block_key,
            LocationProfile.building_type == body.building_type,
        )
        .first()
    )

    now = datetime.now(timezone.utc)

    if existing:
        if existing.building_type_status == "locked":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This block already has a locked profile for this building type. "
                    "Submit a verification to flag a conflict if you believe it has changed."
                ),
            )
        if body.raw_notes:
            separator = "\n---\n" if existing.raw_notes else ""
            existing.raw_notes = (existing.raw_notes or "") + separator + body.raw_notes
            existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return LocationProfileResponse.from_orm_with_protocol(existing)

    workload = derive_workload_class(body.building_type)
    profile = LocationProfile(
        company_id              = caller.company_id,
        block_key               = body.block_key,
        building_type           = body.building_type,
        workload_class          = workload,
        building_type_status    = "pending",
        building_type_agreement_count = 0,
        raw_notes               = body.raw_notes,
        submitted_by            = caller.id,
        submitted_by_name       = caller.name,
        submitted_at            = now,
        created_by              = caller.id,
        created_by_name         = caller.name,
        updated_at              = now,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.get("/", response_model=list[LocationProfileResponse])
def list_profiles(
    block_key:     str | None = Query(None),
    building_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_read),
    db: Session = Depends(get_db),
):
    q = db.query(LocationProfile).filter(LocationProfile.company_id == caller.company_id)
    if block_key:
        q = q.filter(LocationProfile.block_key == block_key)
    if building_type:
        q = q.filter(LocationProfile.building_type == building_type)
    if status_filter:
        q = q.filter(LocationProfile.building_type_status == status_filter)
    q = q.order_by(LocationProfile.block_key, LocationProfile.building_type)
    rows = pg.apply(q).all()
    return [LocationProfileResponse.from_orm_with_protocol(r) for r in rows]


@router.get("/{profile_id}", response_model=LocationProfileResponse)
def get_profile(
    profile_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_read),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(LocationProfile)
        .filter(LocationProfile.id == profile_id, LocationProfile.company_id == caller.company_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.post("/{profile_id}/verify", response_model=LocationProfileResponse)
def verify_building_type(
    profile_id: UUID,
    body: LocationProfileVerify,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_verify),
    db: Session = Depends(get_db),
):
    """Verify or contest the building_type for a profile.

    - If confirmed_building_type matches the stored type: increment agreement_count.
      Promote to verified when count ≥ 1, locked when count ≥ threshold.
    - If it doesn't match a locked record: reset agreement_count to 1 with the
      new type (conflict re-opens review). pending/verified records just update type.
    """
    if body.confirmed_building_type not in BUILDING_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid building_type: {body.confirmed_building_type!r}.",
        )

    profile = (
        db.query(LocationProfile)
        .filter(LocationProfile.id == profile_id, LocationProfile.company_id == caller.company_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    threshold = _get_lock_threshold(db, caller.company_id)
    now = datetime.now(timezone.utc)

    if body.confirmed_building_type == profile.building_type:
        profile.building_type_agreement_count += 1
        profile.verified_by      = caller.id
        profile.verified_by_name = caller.name
        profile.verified_at      = now
        if profile.building_type_status == "pending":
            profile.building_type_status = "verified"
        if profile.building_type_agreement_count >= threshold:
            profile.building_type_status = "locked"
            _auto_nominate_if_eligible(profile)
    else:
        # Conflict — override type and restart count
        profile.building_type             = body.confirmed_building_type
        profile.workload_class            = derive_workload_class(body.confirmed_building_type)
        profile.building_type_status      = "verified"
        profile.building_type_agreement_count = 1
        profile.nomination_status         = None   # pull back from nomination pipeline
        profile.verified_by               = caller.id
        profile.verified_by_name          = caller.name
        profile.verified_at               = now

    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.patch("/{profile_id}/note", response_model=LocationProfileResponse)
def set_operational_note(
    profile_id: UUID,
    body: LocationProfileNotePatch,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_verify),
    db: Session = Depends(get_db),
):
    """Convert raw_notes to a structured operational_note (captain/management)."""
    profile = (
        db.query(LocationProfile)
        .filter(LocationProfile.id == profile_id, LocationProfile.company_id == caller.company_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    now = datetime.now(timezone.utc)
    profile.operational_note = body.operational_note
    profile.note_verified    = False   # reset: editing the note un-verifies it
    profile.note_verified_by = None
    profile.note_verified_by_name = None
    profile.note_verified_at = None
    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.post("/{profile_id}/verify-note", response_model=LocationProfileResponse)
def verify_note(
    profile_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_verify),
    db: Session = Depends(get_db),
):
    """Mark the operational_note as verified (captain/management sign-off)."""
    profile = (
        db.query(LocationProfile)
        .filter(LocationProfile.id == profile_id, LocationProfile.company_id == caller.company_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    if not profile.operational_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Set an operational_note before verifying it.",
        )

    now = datetime.now(timezone.utc)
    profile.note_verified         = True
    profile.note_verified_by      = caller.id
    profile.note_verified_by_name = caller.name
    profile.note_verified_at      = now
    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return LocationProfileResponse.from_orm_with_protocol(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_delete),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(LocationProfile)
        .filter(LocationProfile.id == profile_id, LocationProfile.company_id == caller.company_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    db.delete(profile)
    db.commit()
