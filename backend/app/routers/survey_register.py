"""The survey register (ADR-504): building knowledge kept outside any tenant.

Who may write (D1):
  * the owner: a member of the `super_admin` Cognito group;
  * an admitted contributor: the `surveyor` group AND an active
    `survey_contributors` row. They may never be linked to an employee of the
    excluded company (or of any tenant, if none is configured). This is checked
    on EVERY write, not only at admission.

Platform support staff are not writers: ADR-343 D4 keeps them off anything
holding addresses.

How a door gets recorded (D2, D3):
  1. GET  /survey/blocks?lat&lng     the city's blocks around a point
  2. POST /survey/walks              confirm the protocol, pick one block; the
                                     server re-fetches and snapshots its list
  3. POST /survey/walks/{id}/observations   one door from that snapshot
  4. POST /survey/walks/{id}/close

Reads (D7): the owner sees every observation; a contributor sees their own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_super_admin
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.survey_register import (
    DELIVERY_MODES, DELIVERY_POINTS, SOURCES,
    SurveyContributor, SurveyObservation, SurveyWalk,
)
from app.schemas.building_taxonomy import BUILDING_TYPES
from app.services import survey_blocks
from app.services.address_inventory import AddressSourceUnavailable
from app.services.audit import super_admin_identity, write_audit
from app.services.note_scrub import scrub_note

router = APIRouter(prefix="/survey", tags=["survey-register"])

ATTESTATION = "Made outside any carrier's services, per ADR-504 D2."

# D4: a note may never hold an access code. Refused with the reason rather than
# silently cleaned: the person typing it is right there and can rephrase.
_CODE_WORDS = re.compile(
    r"\b(code|codes|pin|combo|combination|buzz|buzzer|keypad|passcode|password|fob)\b"
    r"|#\s?\d{3,}|\b\d{3,8}\s?#",
    re.IGNORECASE,
)


# ── who is writing ──────────────────────────────────────────────────────────

@dataclass
class Writer:
    sub: str
    owner: bool


def _excluded_company() -> Optional[UUID]:
    """The configured company, or None for the strict any-tenant rule. A value
    that is not a UUID also falls back to strict: a typo in config must never
    quietly let employees write (fail closed)."""
    raw = (settings.survey_excluded_company_id or "").strip()
    try:
        return UUID(raw) if raw else None
    except ValueError:
        return None


def _assert_not_excluded(db: Session, sub: str) -> None:
    q = db.query(Employee.id).filter(Employee.cognito_sub == sub)
    company = _excluded_company()
    if company is not None:
        q = q.filter(Employee.company_id == company)
    if q.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is linked to a delivery company's employee record "
                   "and cannot write the survey register.",
        )


def get_writer(current_user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)) -> Writer:
    sub = current_user.get("id")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in first.")
    groups = current_user.get("cognito_groups", [])
    if "super_admin" in groups:
        return Writer(sub=sub, owner=True)
    if "surveyor" not in groups:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The survey register is by invitation only.")
    active = (db.query(SurveyContributor.id)
              .filter(SurveyContributor.cognito_sub == sub,
                      SurveyContributor.revoked_at.is_(None))
              .first())
    if active is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The survey register is by invitation only.")
    _assert_not_excluded(db, sub)
    return Writer(sub=sub, owner=False)


# ── schemas ─────────────────────────────────────────────────────────────────

class AddressOut(BaseModel):
    index: int
    address: str
    bin: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class BlockOut(BaseModel):
    block_key: str
    street: str
    description: str
    addresses: list[AddressOut]


class StartWalkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=40.4, le=41.0)       # New York City
    lng: float = Field(ge=-74.3, le=-73.6)
    radius_m: int = Field(150, ge=25, le=survey_blocks.MAX_RADIUS_M)
    block_key: str = Field(min_length=1, max_length=100)
    attest_off_shift: bool
    attest_unbranded: bool
    attest_as_self: bool

    @model_validator(mode="after")
    def _all_attested(self):
        if not (self.attest_off_shift and self.attest_unbranded and self.attest_as_self):
            raise ValueError(
                "All three must be true: off-shift; no branded vehicle, uniform or work "
                "device; asking as yourself, not as a driver (ADR-504 D2)."
            )
        return self


class WalkOut(BaseModel):
    id: UUID
    block_key: str
    street: str
    started_at: datetime
    closed_at: Optional[datetime] = None
    addresses: list[AddressOut]
    recorded: list[int]          # indexes already observed on this walk


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address_index: int = Field(ge=0, le=5000)
    source: Literal[SOURCES]  # type: ignore[valid-type]
    building_type: str = Field(min_length=1, max_length=30)
    delivery_point: Optional[Literal[DELIVERY_POINTS]] = None  # type: ignore[valid-type]
    entrance_side: Optional[str] = Field(None, max_length=120)
    security_desk: Optional[bool] = None
    sign_in_required: Optional[bool] = None
    delivery_mode: Optional[Literal[DELIVERY_MODES]] = None  # type: ignore[valid-type]
    floors: Optional[int] = Field(None, ge=1, le=200)
    opens_at: Optional[time] = None
    closes_at: Optional[time] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    note: Optional[str] = Field(None, max_length=500)


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    walk_id: UUID
    address: str
    bin: Optional[str] = None
    observed_on: date
    source: str
    building_type: str
    delivery_point: Optional[str] = None
    entrance_side: Optional[str] = None
    security_desk: Optional[bool] = None
    sign_in_required: Optional[bool] = None
    delivery_mode: Optional[str] = None
    floors: Optional[int] = None
    opens_at: Optional[time] = None
    closes_at: Optional[time] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    note: Optional[str] = None
    mine: bool = False


class ContributorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cognito_sub: str = Field(min_length=8, max_length=255)
    display_name: str = Field(min_length=1, max_length=100)
    agreement_version: str = Field(min_length=1, max_length=20)
    agreement_signed_on: date


class ContributorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    agreement_version: str
    agreement_signed_on: date
    admitted_at: datetime
    revoked_at: Optional[datetime] = None


class MeOut(BaseModel):
    role: Literal["owner", "contributor"]


# ── helpers ─────────────────────────────────────────────────────────────────

def _addresses(walk: SurveyWalk) -> list[AddressOut]:
    return [AddressOut(index=i, **a) for i, a in enumerate(walk.addresses or [])]


def _walk_out(db: Session, walk: SurveyWalk) -> WalkOut:
    done = {a for (a,) in db.query(SurveyObservation.address)
            .filter(SurveyObservation.walk_id == walk.id).all()}
    return WalkOut(
        id=walk.id, block_key=walk.block_key, street=walk.street,
        started_at=walk.started_at, closed_at=walk.closed_at,
        addresses=_addresses(walk),
        recorded=[i for i, a in enumerate(walk.addresses or []) if a["address"] in done],
    )


def _own_walk(db: Session, walk_id: UUID, writer: Writer) -> SurveyWalk:
    walk = (db.query(SurveyWalk)
            .filter(SurveyWalk.id == walk_id, SurveyWalk.writer_sub == writer.sub)
            .first())
    if walk is None:
        raise HTTPException(status_code=404, detail="Walk not found.")
    return walk


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/me", response_model=MeOut)
def survey_me(writer: Writer = Depends(get_writer)):
    return MeOut(role="owner" if writer.owner else "contributor")


class PointOut(BaseModel):
    lat: float
    lng: float


@router.get("/locate", response_model=PointOut)
def survey_locate(
    address: str = Query(..., min_length=3, max_length=200),
    borough: Literal["manhattan", "brooklyn", "queens", "bronx", "staten island"] = "manhattan",
    writer: Writer = Depends(get_writer),
):
    """A typed address to a point, for finding blocks without GPS.

    GeoClient directly (the city's public geocoder). NOT `resolve_address`: that
    consults the PlaceType Library first and writes back into it, and the
    register must neither read nor write tenant-derived data (ADR-504 D6).
    """
    from app.tasks.enrich_manifest import _geoclient_normalise
    try:
        geo = _geoclient_normalise(address, borough=borough)
    except Exception:
        raise HTTPException(status_code=503, detail="The city's geocoder is unavailable. Use your location instead.")
    if geo is None or geo.lat is None or geo.lng is None:
        raise HTTPException(status_code=404, detail="The city doesn't recognise that address.")
    return PointOut(lat=geo.lat, lng=geo.lng)


@router.get("/blocks", response_model=list[BlockOut])
def survey_blocks_near(
    lat: float = Query(..., ge=40.4, le=41.0),
    lng: float = Query(..., ge=-74.3, le=-73.6),
    radius_m: int = Query(150, ge=25, le=survey_blocks.MAX_RADIUS_M),
    writer: Writer = Depends(get_writer),
):
    """The city's blocks around a point. Public data; nothing is stored."""
    try:
        blocks = survey_blocks.blocks_near(lat, lng, radius_m)
    except AddressSourceUnavailable:
        raise HTTPException(status_code=503, detail="The city's address list is unavailable. Try again shortly.")
    return [BlockOut(block_key=b.block_key, street=b.street, description=b.description,
                     addresses=[AddressOut(index=i, **a) for i, a in enumerate(b.doors)])
            for b in blocks]


@router.post("/walks", response_model=WalkOut, status_code=status.HTTP_201_CREATED)
def start_walk(body: StartWalkIn, writer: Writer = Depends(get_writer),
               db: Session = Depends(get_db)):
    """Begin a walk of one block. The server fetches the block's list itself."""
    try:
        blocks = survey_blocks.blocks_near(body.lat, body.lng, body.radius_m)
    except AddressSourceUnavailable:
        raise HTTPException(status_code=503, detail="The city's address list is unavailable. Try again shortly.")
    block = next((b for b in blocks if b.block_key == body.block_key), None)
    if block is None or not block.doors:
        raise HTTPException(status_code=422, detail="That block is not on the city's list near this point.")

    walk = SurveyWalk(
        writer_sub=writer.sub, block_key=block.block_key, street=block.street,
        addresses=block.doors, source_dataset=settings.socrata_addresspoint_dataset,
        fetched_at=datetime.now(timezone.utc),
        attest_off_shift=True, attest_unbranded=True, attest_as_self=True,
    )
    db.add(walk)
    db.flush()
    write_audit(db, action_type="survey.walk.start", target_table="survey_walks",
                target_id=str(walk.id), actor_id=None, company_id=None,
                detail={"block_key": block.block_key, "doors": len(block.doors),
                        "writer": "owner" if writer.owner else "contributor"})
    db.commit()
    db.refresh(walk)
    return _walk_out(db, walk)


@router.get("/walks", response_model=list[WalkOut])
def my_walks(writer: Writer = Depends(get_writer), db: Session = Depends(get_db),
             limit: int = Query(20, ge=1, le=100)):
    walks = (db.query(SurveyWalk).filter(SurveyWalk.writer_sub == writer.sub)
             .order_by(SurveyWalk.started_at.desc()).limit(limit).all())
    return [_walk_out(db, w) for w in walks]


@router.get("/walks/{walk_id}", response_model=WalkOut)
def get_walk(walk_id: UUID, writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    return _walk_out(db, _own_walk(db, walk_id, writer))


@router.post("/walks/{walk_id}/observations", response_model=ObservationOut,
             status_code=status.HTTP_201_CREATED)
def record_observation(walk_id: UUID, body: ObservationIn,
                       writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    """One door from the walk's list. The address and BIN come from the snapshot,
    never from the request."""
    walk = _own_walk(db, walk_id, writer)
    if walk.closed_at is not None:
        raise HTTPException(status_code=409, detail="This walk is closed. Start a new one to re-visit.")
    if body.address_index >= len(walk.addresses or []):
        raise HTTPException(status_code=422, detail="That door is not on this walk's list.")
    if body.building_type not in BUILDING_TYPES:
        raise HTTPException(status_code=422, detail="Unknown building type.")
    if body.note and _CODE_WORDS.search(body.note):
        raise HTTPException(status_code=422,
                            detail="Notes can't hold access or door codes. Describe the entrance instead.")
    if body.entrance_side and _CODE_WORDS.search(body.entrance_side):
        raise HTTPException(status_code=422, detail="This field can't hold access or door codes.")

    door = walk.addresses[body.address_index]
    already = (db.query(SurveyObservation.id)
               .filter(SurveyObservation.walk_id == walk.id,
                       SurveyObservation.address == door["address"]).first())
    if already is not None:
        raise HTTPException(status_code=409, detail="Already recorded on this walk.")

    obs = SurveyObservation(
        walk_id=walk.id, writer_sub=writer.sub,
        address=door["address"], bin=door.get("bin"),
        observed_on=date.today(), source=body.source,
        building_type=body.building_type, delivery_point=body.delivery_point,
        entrance_side=(body.entrance_side or None), security_desk=body.security_desk,
        sign_in_required=body.sign_in_required, delivery_mode=body.delivery_mode,
        floors=body.floors, opens_at=body.opens_at, closes_at=body.closes_at,
        break_start=body.break_start, break_end=body.break_end,
        note=scrub_note(body.note)[0] if body.note else None,
        attestation=ATTESTATION,
    )
    db.add(obs)
    db.flush()
    # Ids and the source only: an address in an audit snapshot is a copy no
    # erasure or retention reaches (ADR-493 D8). The observation row IS the
    # provenance record; this marks that it was written and by which kind of writer.
    write_audit(db, action_type="survey.observation.record", target_table="survey_observations",
                target_id=str(obs.id), actor_id=None, company_id=None,
                detail={"walk_id": str(walk.id), "source": body.source,
                        "writer": "owner" if writer.owner else "contributor"})
    db.commit()
    db.refresh(obs)
    out = ObservationOut.model_validate(obs)
    out.mine = True
    return out


@router.post("/walks/{walk_id}/close", response_model=WalkOut)
def close_walk(walk_id: UUID, writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    walk = _own_walk(db, walk_id, writer)
    if walk.closed_at is not None:
        raise HTTPException(status_code=409, detail="This walk is already closed.")
    walk.closed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db, action_type="survey.walk.close", target_table="survey_walks",
                target_id=str(walk.id), actor_id=None, company_id=None,
                detail={"writer": "owner" if writer.owner else "contributor"})
    db.commit()
    db.refresh(walk)
    return _walk_out(db, walk)


@router.get("/observations", response_model=list[ObservationOut])
def list_observations(
    bin: Optional[str] = Query(None, max_length=20),
    block_key: Optional[str] = Query(None, max_length=100),
    limit: int = Query(200, ge=1, le=1000),
    writer: Writer = Depends(get_writer), db: Session = Depends(get_db),
):
    """The owner reads everything; a contributor reads their own (D7)."""
    q = db.query(SurveyObservation)
    if not writer.owner:
        q = q.filter(SurveyObservation.writer_sub == writer.sub)
    if bin:
        q = q.filter(SurveyObservation.bin == bin)
    if block_key:
        q = q.join(SurveyWalk, SurveyWalk.id == SurveyObservation.walk_id).filter(
            SurveyWalk.block_key == block_key)
    rows = q.order_by(SurveyObservation.observed_at.desc()).limit(limit).all()
    out = []
    for r in rows:
        o = ObservationOut.model_validate(r)
        o.mine = r.writer_sub == writer.sub
        out.append(o)
    return out


# ── contributors (owner only) ───────────────────────────────────────────────

@router.get("/contributors", response_model=list[ContributorOut])
def list_contributors(_: dict = Depends(get_super_admin), db: Session = Depends(get_db)):
    return db.query(SurveyContributor).order_by(SurveyContributor.admitted_at.desc()).all()


@router.post("/contributors", response_model=ContributorOut, status_code=status.HTTP_201_CREATED)
def admit_contributor(body: ContributorIn, super_admin: dict = Depends(get_super_admin),
                      db: Session = Depends(get_db)):
    """Admit someone who has signed the contributor agreement (D1)."""
    _assert_not_excluded(db, body.cognito_sub)
    if db.query(SurveyContributor.id).filter(
            SurveyContributor.cognito_sub == body.cognito_sub).first() is not None:
        raise HTTPException(status_code=409, detail="That account is already a contributor.")
    c = SurveyContributor(
        cognito_sub=body.cognito_sub, display_name=body.display_name,
        agreement_version=body.agreement_version, agreement_signed_on=body.agreement_signed_on,
        admitted_by=(super_admin.get("id") or "")[:64] or None,
    )
    db.add(c)
    db.flush()
    write_audit(db, action_type="survey.contributor.admit", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail={**super_admin_identity(super_admin),
                        "agreement_version": body.agreement_version})
    db.commit()
    db.refresh(c)
    return c


@router.post("/contributors/{contributor_id}/revoke", response_model=ContributorOut)
def revoke_contributor(contributor_id: UUID, super_admin: dict = Depends(get_super_admin),
                       db: Session = Depends(get_db)):
    c = db.query(SurveyContributor).filter(SurveyContributor.id == contributor_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    if c.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Already revoked.")
    c.revoked_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db, action_type="survey.contributor.revoke", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail=super_admin_identity(super_admin))
    db.commit()
    db.refresh(c)
    return c
