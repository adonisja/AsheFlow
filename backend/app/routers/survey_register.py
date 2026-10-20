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

Who walks what (ADR-513):
  * the owner or platform support declares AREAS from public boundaries;
  * writers CLAIM a block in an open area for 48 hours, then start its walk
    from the claim. A block inside an open area cannot be walked any other way;
    outside every area, only the owner may walk (scouting, D5);
  * progress is derived (services/survey_progress.py): a done door is locked for
    every writer, a block is done when its last door is, and it re-opens whole
    after REVISIT_DAYS. "Finish walk" with doors left is a pause, not a finish.
"""
from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_platform_staff, get_platform_user, get_super_admin
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.survey_register import (
    AREA_KINDS, CLAIM_HOURS, DAY_STATUS, DELIVERY_MODES, DELIVERY_POINTS, MAX_ACTIVE_CLAIMS,
    MAX_DELIVERY_POINTS, REVISIT_DAYS, SOURCES, TRISTATE,
    SurveyArea, SurveyAreaBlock, SurveyBlockClaim, SurveyContributor, SurveyDeliveryPoint,
    SurveyDoorUnlock, SurveyObservation, SurveyReceivesFor, SurveyWalk,
)
from app.schemas.building_taxonomy import BUILDING_TYPES
from app.services import account_security, mfa_containment, survey_blocks, survey_progress
from app.services.address_inventory import AddressSourceUnavailable
from app.services.audit import super_admin_identity, write_audit
from app.services.email import send_claim_released_notice, send_credentials_email, send_surveyor_mfa_reset_notice
from app.services.note_scrub import scrub_note

logger = logging.getLogger(__name__)
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


def get_writer(current_user: dict = Depends(get_platform_user),
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

class NeighbourOut(BaseModel):
    address: str
    bin: Optional[str] = None


class AddressOut(BaseModel):
    index: int
    address: str
    bin: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    # ADR-504 D8, set when a walk starts (absent on the block-list preview).
    city_block: Optional[str] = None
    sides: list[str] = []                   # [B] the streets this block faces, ordered
    neighbours: list[NeighbourOut] = []     # [A] doors on the same city block


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
    # ADR-513 D6: indexes of doors DONE on this block, by any writer on any walk
    # in the current cycle, and therefore locked. Walks from before ADR-513 have
    # no borough and keep the old meaning (this walk only).
    recorded: list[int]
    area_id: Optional[UUID] = None
    block_state: Literal["open", "in_progress", "done"] = "open"


class DeliveryPointIn(BaseModel):
    """[B] One place deliveries go."""
    model_config = ConfigDict(extra="forbid")
    point: Literal[DELIVERY_POINTS]  # type: ignore[valid-type]
    side: Optional[str] = Field(None, max_length=120)
    floor: Optional[int] = Field(None, ge=-5, le=200)
    which_packages: Optional[str] = Field(None, max_length=120)


class DayHoursIn(BaseModel):
    """[C] One day group: open (with both times), closed, or didn't find out."""
    model_config = ConfigDict(extra="forbid")
    status: Literal[DAY_STATUS] = "unknown"  # type: ignore[valid-type]
    open: Optional[time] = None
    close: Optional[time] = None

    @model_validator(mode="after")
    def _times_match_status(self):
        if self.status == "open" and (self.open is None or self.close is None):
            raise ValueError("Open hours need both an opening and a closing time.")
        if self.status != "open" and (self.open is not None or self.close is not None):
            raise ValueError("Times are only given when the status is open.")
        return self


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address_index: int = Field(ge=0, le=5000)
    source: Literal[SOURCES] = "observed"  # type: ignore[valid-type]
    # [F] A door on the city list that is not a delivery point. Nothing else is
    # required, and no delivery facts may be given.
    not_a_delivery_point: bool = False
    building_type: Optional[str] = Field(None, min_length=1, max_length=30)
    delivery_points: list[DeliveryPointIn] = Field(default_factory=list, max_length=MAX_DELIVERY_POINTS)
    # [A] Indexes into this door's `neighbours` (its city block), never addresses.
    receives_for: list[int] = Field(default_factory=list, max_length=50)
    security_desk: Literal[TRISTATE] = "unknown"  # type: ignore[valid-type]
    sign_in_required: Literal[TRISTATE] = "unknown"  # type: ignore[valid-type]
    delivery_mode: Optional[Literal[DELIVERY_MODES]] = None  # type: ignore[valid-type]
    floors: Optional[int] = Field(None, ge=1, le=200)
    weekday: DayHoursIn = Field(default_factory=DayHoursIn)
    saturday: DayHoursIn = Field(default_factory=DayHoursIn)
    sunday: DayHoursIn = Field(default_factory=DayHoursIn)
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    note: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.not_a_delivery_point:
            if self.delivery_points or self.receives_for or self.delivery_mode or self.floors:
                raise ValueError("A door that is not a delivery point carries no delivery details.")
        elif not self.building_type:
            raise ValueError("Choose a building type.")
        if len(set(self.receives_for)) != len(self.receives_for):
            raise ValueError("Each door may be listed once.")
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("A break needs both a start and an end.")
        return self


class DeliveryPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    position: int
    point: str
    side: Optional[str] = None
    floor: Optional[int] = None
    which_packages: Optional[str] = None


class DayHoursOut(BaseModel):
    status: str
    open: Optional[time] = None
    close: Optional[time] = None


class ObservationOut(BaseModel):
    id: UUID
    walk_id: UUID
    address: str
    bin: Optional[str] = None
    observed_on: date
    source: str
    not_a_delivery_point: bool
    building_type: str
    delivery_points: list[DeliveryPointOut]
    receives_for: list[NeighbourOut]
    security_desk: str
    sign_in_required: str
    delivery_mode: Optional[str] = None
    floors: Optional[int] = None
    weekday: DayHoursOut
    saturday: DayHoursOut
    sunday: DayHoursOut
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


class ContributorInviteIn(BaseModel):
    """ADR-509 D1: create a NEW account, grant `surveyor`, and admit it."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    agreement_version: str = Field(min_length=1, max_length=20)
    agreement_signed_on: date
    # The caller confirms they hold the signed agreement. Must be TRUE.
    confirm_agreement_signed: bool

    @model_validator(mode="after")
    def _signed(self):
        if not self.confirm_agreement_signed:
            raise ValueError("Only admit someone who has signed the contributor agreement.")
        if self.agreement_signed_on > date.today():
            raise ValueError("The signing date can't be in the future.")
        return self


class ContributorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    # ADR-509 D3: shown to platform staff who manage contributors.
    email: Optional[str] = None
    cognito_username: Optional[str] = None
    agreement_version: str
    agreement_signed_on: date
    admitted_at: datetime
    revoked_at: Optional[datetime] = None


class InviteOut(BaseModel):
    contributor: ContributorOut
    email_delivered: bool
    # Only when the credentials email failed (ADR-442 D2): shown once, never stored.
    temp_password: Optional[str] = None


class MeOut(BaseModel):
    role: Literal["owner", "contributor"]


# ── helpers ─────────────────────────────────────────────────────────────────

def _addresses(walk: SurveyWalk) -> list[AddressOut]:
    return [AddressOut(index=i, **a) for i, a in enumerate(walk.addresses or [])]


def _walk_out(db: Session, walk: SurveyWalk) -> WalkOut:
    if walk.borough is None:
        done = {a for (a,) in db.query(SurveyObservation.address)
                .filter(SurveyObservation.walk_id == walk.id).all()}
        state = "in_progress" if done else "open"
    else:
        p = survey_progress.progress_for(db, walk.borough, walk.block_key, [], _now())
        done, state = p.done, p.state
    return WalkOut(
        id=walk.id, block_key=walk.block_key, street=walk.street,
        started_at=walk.started_at, closed_at=walk.closed_at,
        addresses=_addresses(walk),
        recorded=[i for i, a in enumerate(walk.addresses or []) if a["address"] in done],
        area_id=walk.area_id, block_state=state,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_claims(db: Session):
    """Claims in force: not released and not lapsed. A lapse needs no write."""
    return db.query(SurveyBlockClaim).filter(SurveyBlockClaim.released_at.is_(None),
                                            SurveyBlockClaim.expires_at > _now())


def _open_area_block(db: Session, borough: str, block_key: str) -> Optional[SurveyAreaBlock]:
    return (db.query(SurveyAreaBlock)
            .join(SurveyArea, SurveyArea.id == SurveyAreaBlock.area_id)
            .filter(SurveyArea.closed_at.is_(None),
                    SurveyAreaBlock.borough == borough, SurveyAreaBlock.block_key == block_key)
            .first())


def _lock_block(db: Session, borough: str, block_key: str) -> None:
    """Serialise claims on one block across every area (an NTA and a Community
    District can overlap). A transaction-scoped advisory lock on Postgres; SQLite
    has one writer anyway."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                   {"k": f"survey-block:{borough}:{block_key}"})


def _obs_out(db: Session, r: SurveyObservation, writer: Writer) -> ObservationOut:
    points = (db.query(SurveyDeliveryPoint).filter(SurveyDeliveryPoint.observation_id == r.id)
              .order_by(SurveyDeliveryPoint.position).all())
    rf = (db.query(SurveyReceivesFor).filter(SurveyReceivesFor.observation_id == r.id)
          .order_by(SurveyReceivesFor.address).all())
    day = lambda g: DayHoursOut(status=getattr(r, f"{g}_status"),
                                open=getattr(r, f"{g}_open"), close=getattr(r, f"{g}_close"))
    return ObservationOut(
        id=r.id, walk_id=r.walk_id, address=r.address, bin=r.bin, observed_on=r.observed_on,
        source=r.source, not_a_delivery_point=r.not_a_delivery_point, building_type=r.building_type,
        delivery_points=[DeliveryPointOut.model_validate(p) for p in points],
        receives_for=[NeighbourOut(address=x.address, bin=x.bin) for x in rf],
        security_desk=r.security_desk, sign_in_required=r.sign_in_required,
        delivery_mode=r.delivery_mode, floors=r.floors,
        weekday=day("weekday"), saturday=day("saturday"), sunday=day("sunday"),
        break_start=r.break_start, break_end=r.break_end, note=r.note,
        mine=(r.writer_sub == writer.sub),
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
    # ADR-513 D3/D5: a block in an open area is walked from a claim, by anyone;
    # outside every area, only the owner walks (scouting).
    if block.borough and _open_area_block(db, block.borough, block.block_key) is not None:
        raise HTTPException(status_code=409,
                            detail="This block is in a survey area. Claim it there to walk it.")
    if not writer.owner:
        raise HTTPException(status_code=403,
                            detail="Contributors walk blocks inside survey areas. Claim one from the list.")
    return _create_walk(db, writer, block, area_id=None)


def _create_walk(db: Session, writer: Writer, block: survey_blocks.Block,
                 area_id: Optional[UUID], claim: Optional[SurveyBlockClaim] = None) -> WalkOut:
    # D8: each door's city block, the streets that block faces, and its
    # same-block neighbours, snapshotted with the list (best effort).
    doors = survey_blocks.enrich_doors(block.doors)
    walk = SurveyWalk(
        writer_sub=writer.sub, block_key=block.block_key, street=block.street,
        addresses=doors, source_dataset=settings.socrata_addresspoint_dataset,
        fetched_at=datetime.now(timezone.utc),
        attest_off_shift=True, attest_unbranded=True, attest_as_self=True,
        borough=block.borough or None, area_id=area_id,
    )
    db.add(walk)
    db.flush()
    if claim is not None:
        claim.walk_id = walk.id      # same transaction: never a walk without its claim
    write_audit(db, action_type="survey.walk.start", target_table="survey_walks",
                target_id=str(walk.id), actor_id=None, company_id=None,
                detail={"block_key": block.block_key, "doors": len(block.doors),
                        "area_id": str(area_id) if area_id else None,
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
    if body.building_type is not None and body.building_type not in BUILDING_TYPES:
        raise HTTPException(status_code=422, detail="Unknown building type.")
    texts = [body.note] + [p.side for p in body.delivery_points] + [p.which_packages for p in body.delivery_points]
    if any(t and _CODE_WORDS.search(t) for t in texts):
        raise HTTPException(status_code=422,
                            detail="This can't hold access or door codes. Describe the entrance instead.")

    door = walk.addresses[body.address_index]
    already = (db.query(SurveyObservation.id)
               .filter(SurveyObservation.walk_id == walk.id,
                       SurveyObservation.address == door["address"]).first())
    if already is not None:
        raise HTTPException(status_code=409, detail="Already recorded on this walk.")
    # ADR-513 D6: done on ANY walk of this block in the current cycle is locked.
    # The tick in the list is the convenience; this is the lock.
    if walk.borough is not None:
        p = survey_progress.progress_for(db, walk.borough, walk.block_key,
                                         [d["address"] for d in walk.addresses], _now())
        if door["address"] in p.done:
            raise HTTPException(status_code=409,
                                detail="Someone has already recorded this door. It's locked until the block re-opens.")
    neighbours = door.get("neighbours") or []
    if any(i >= len(neighbours) for i in body.receives_for):
        raise HTTPException(status_code=422, detail="Only doors on the same city block can be chosen.")

    obs = SurveyObservation(
        walk_id=walk.id, writer_sub=writer.sub,
        address=door["address"], bin=door.get("bin"),
        observed_on=date.today(), source=body.source,
        not_a_delivery_point=body.not_a_delivery_point,
        building_type=body.building_type or "unknown",
        security_desk=body.security_desk, sign_in_required=body.sign_in_required,
        delivery_mode=body.delivery_mode, floors=body.floors,
        weekday_status=body.weekday.status, weekday_open=body.weekday.open, weekday_close=body.weekday.close,
        saturday_status=body.saturday.status, saturday_open=body.saturday.open, saturday_close=body.saturday.close,
        sunday_status=body.sunday.status, sunday_open=body.sunday.open, sunday_close=body.sunday.close,
        break_start=body.break_start, break_end=body.break_end,
        note=scrub_note(body.note)[0] if body.note else None,
        attestation=ATTESTATION,
    )
    db.add(obs)
    db.flush()
    for i, p in enumerate(body.delivery_points, start=1):
        db.add(SurveyDeliveryPoint(observation_id=obs.id, position=i, point=p.point,
                                   side=(p.side or None), floor=p.floor,
                                   which_packages=(p.which_packages or None)))
    for i in body.receives_for:
        n = neighbours[i]
        db.add(SurveyReceivesFor(observation_id=obs.id, address=n["address"], bin=n.get("bin")))
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
    return _obs_out(db, obs, writer)


@router.post("/walks/{walk_id}/close", response_model=WalkOut)
def close_walk(walk_id: UUID, writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    walk = _own_walk(db, walk_id, writer)
    if walk.closed_at is not None:
        raise HTTPException(status_code=409, detail="This walk is already closed.")
    walk.closed_at = datetime.now(timezone.utc)
    # ADR-513 D6: finishing with doors left is a PAUSE. The claim goes back, the
    # block stays in progress, and the next claim continues it.
    for c in (db.query(SurveyBlockClaim)
              .filter(SurveyBlockClaim.walk_id == walk.id, SurveyBlockClaim.released_at.is_(None))):
        c.released_at, c.release_reason = walk.closed_at, "walk_closed"
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
    return [_obs_out(db, r, writer) for r in rows]


# ── contributors (ADR-509: both platform roles, bounded) ────────────────────

@router.get("/contributors", response_model=list[ContributorOut])
def list_contributors(_: dict = Depends(get_platform_staff), db: Session = Depends(get_db)):
    """ADR-509 D3: both platform roles. Contributors' names and emails only;
    nothing from the register itself."""
    return db.query(SurveyContributor).order_by(SurveyContributor.admitted_at.desc()).all()


@router.post("/contributors", response_model=ContributorOut, status_code=status.HTTP_201_CREATED)
def admit_contributor(body: ContributorIn, super_admin: dict = Depends(get_super_admin),
                      db: Session = Depends(get_db)):
    """Admit an EXISTING account by its sub (D1). Super admin only: attaching the
    register to an account that already exists is the escalation ADR-509 keeps
    away from support."""
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


def _staff_identity(claims: dict) -> dict:
    """`super_admin_identity`, with the caller's REAL role. That helper always
    writes "super_admin"; on an endpoint support can call (ADR-509), it would
    audit a support user's action as the owner's."""
    groups = claims.get("cognito_groups", [])
    return {**super_admin_identity(claims),
            "actor_kind": "super_admin" if "super_admin" in groups else "platform_support"}


def _temp_password() -> str:
    """The ADR-444 shape (platform_alerts / registration): satisfies the pool
    policy without depending on its exact settings."""
    chars = (
        [secrets.choice(string.ascii_uppercase) for _ in range(2)]
        + [secrets.choice(string.digits) for _ in range(3)]
        + [secrets.choice(string.ascii_lowercase) for _ in range(2)]
        + [secrets.choice("!@#$%^&*") for _ in range(2)]
    )
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _employee_email_excluded(db: Session, email: str) -> bool:
    q = db.query(Employee.id).filter(Employee.email.ilike(email))
    company = _excluded_company()
    if company is not None:
        q = q.filter(Employee.company_id == company)
    return q.first() is not None


@router.post("/contributors/invite", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def invite_contributor(body: ContributorInviteIn, staff: dict = Depends(get_platform_staff),
                       db: Session = Depends(get_db)):
    """ADR-509 D1: create a NEW account in `surveyor` and admit it, in one step.

    Open to platform support: an explicit exception to ADR-343 D1, bounded so it
    cannot escalate anyone. Only brand-new accounts (an existing email gives 409),
    never the caller's own, never an excluded-company employee's.
    """
    from app.routers.platform_alerts import _derive_platform_username

    email = str(body.email).strip().lower()
    if email == (staff.get("email") or "").strip().lower():
        raise HTTPException(status_code=403, detail="You can't admit yourself as a contributor.")
    if _employee_email_excluded(db, email):
        raise HTTPException(status_code=403,
                            detail="That email belongs to a delivery company's employee record "
                                   "and can't be a contributor.")

    client = _cognito()
    pool = settings.aws_cognito_user_pool_id
    try:
        existing = client.list_users(UserPoolId=pool, Filter=f'email = "{email}"', Limit=1)
    except (ClientError, BotoCoreError) as exc:
        logger.error("survey invite: user lookup failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not check for an existing account.")
    if existing.get("Users"):
        raise HTTPException(
            status_code=409,
            detail="An account with that email already exists. Ask the owner to admit it.")

    username = _derive_platform_username(client, body.name)
    temp_password = _temp_password()
    try:
        created = client.admin_create_user(
            UserPoolId=pool, Username=username, TemporaryPassword=temp_password,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": body.name},
            ],
        )
        sub = next(a["Value"] for a in created["User"]["Attributes"] if a["Name"] == "sub")
        # Not MFA-privileged, so granted now (unlike platform staff, ADR-397).
        client.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName="surveyor")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        logger.error("survey invite: account create failed: %s", code)
        if code == "UsernameExistsException":
            raise HTTPException(status_code=409, detail="An account with that name already exists.")
        raise HTTPException(status_code=502, detail="Could not create the account.")
    except (BotoCoreError, StopIteration) as exc:
        logger.error("survey invite: account create failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not create the account.")

    try:
        c = SurveyContributor(
            cognito_sub=sub, cognito_username=username, email=email,
            display_name=body.name, agreement_version=body.agreement_version,
            agreement_signed_on=body.agreement_signed_on,
            admitted_by=(staff.get("id") or "")[:64] or None,
        )
        db.add(c)
        db.flush()
        write_audit(db, action_type="survey.contributor.invite", target_table="survey_contributors",
                    target_id=str(c.id), actor_id=None, company_id=None,
                    detail={**_staff_identity(staff), "username": username,
                            "agreement_version": body.agreement_version})
        db.commit()
        db.refresh(c)
    except Exception:
        # No half-made account: the Cognito user goes if the row did not land.
        db.rollback()
        try:
            client.admin_delete_user(UserPoolId=pool, Username=username)
        except (ClientError, BotoCoreError) as exc:
            logger.error("survey invite: cleanup of %s failed: %s", username, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not admit the contributor. Nothing was created.")

    email_delivered = True
    try:
        send_credentials_email(to_email=email, employee_name=body.name,
                               username=username, temp_password=temp_password)
    except Exception as exc:
        logger.error("survey invite: credentials email failed: %s", type(exc).__name__)
        email_delivered = False

    return InviteOut(contributor=ContributorOut.model_validate(c), email_delivered=email_delivered,
                     temp_password=None if email_delivered else temp_password)


@router.post("/contributors/{contributor_id}/revoke", response_model=ContributorOut)
def revoke_contributor(contributor_id: UUID, staff: dict = Depends(get_platform_staff),
                       db: Session = Depends(get_db)):
    """Both platform roles (ADR-509 D2): revoking only reduces access. Also takes
    the account out of `surveyor`, best effort: the row is what `get_writer` reads."""
    c = db.query(SurveyContributor).filter(SurveyContributor.id == contributor_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    if c.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Already revoked.")
    c.revoked_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db, action_type="survey.contributor.revoke", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail=_staff_identity(staff))
    db.commit()
    db.refresh(c)
    if c.cognito_username:
        try:
            _cognito().admin_remove_user_from_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=c.cognito_username, GroupName="surveyor")
        except (ClientError, BotoCoreError) as exc:
            logger.warning("survey revoke: group removal failed: %s", type(exc).__name__)
    return c


# ── ADR-513: areas, claims, and locked doors ────────────────────────────────

_NTA_CODE = re.compile(r"^(MN|BX|BK|QN|SI)\d{4}$")
_CD_CODE = re.compile(r"^[1-5]\d{2}$")


class AreaIn(BaseModel):
    """D1: a public boundary by its official code, and why it is being surveyed."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal[AREA_KINDS]  # type: ignore[valid-type]
    code: str = Field(min_length=3, max_length=10)
    reason: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def _code_shape(self):
        self.code = self.code.strip().upper()
        self.reason = self.reason.strip()
        pattern = _NTA_CODE if self.kind == "nta" else _CD_CODE
        if not pattern.match(self.code):
            raise ValueError("Use the city's code: an NTA like MN0401, or a community district like 104.")
        if len(self.reason) < 3:
            raise ValueError("Say why this area is being surveyed.")
        return self


class AreaOut(BaseModel):
    id: UUID
    kind: str
    code: str
    name: str
    reason: str
    declared_by_kind: str
    declared_at: datetime
    closed_at: Optional[datetime] = None
    blocks_total: int
    blocks_done: int
    blocks_in_progress: int
    doors_total: int
    doors_done: int
    last_activity: Optional[datetime] = None


class AreaBlockOut(BaseModel):
    id: UUID
    borough: str
    block_key: str
    street: str
    description: str
    state: Literal["open", "in_progress", "done"]
    doors_done: int
    doors_total: int
    reopens_on: Optional[date] = None
    last_activity: Optional[datetime] = None
    # "mine" | "taken" | None. Who holds it is never shown to other writers.
    claim: Optional[Literal["mine", "taken"]] = None
    claim_id: Optional[UUID] = None
    distance_m: Optional[int] = None


class AttestIn(BaseModel):
    """ADR-504 D2, re-confirmed at the start of every walk."""
    model_config = ConfigDict(extra="forbid")
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


class ClaimOut(BaseModel):
    id: UUID
    area_id: UUID
    area_name: str
    area_block_id: UUID
    street: str
    description: str
    claimed_at: datetime
    expires_at: datetime
    walk_id: Optional[UUID] = None
    walk_open: bool = False
    doors_done: int
    doors_total: int


class UnlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    walk_id: UUID                       # identifies borough + block without trusting either
    address_index: int = Field(ge=0, le=5000)
    reason: str = Field(min_length=3, max_length=200)


class UnlockOut(BaseModel):
    address: str
    block_state: Literal["open", "in_progress", "done"]


@dataclass
class AreaViewer:
    sub: str
    writer: Optional[Writer]            # None for platform support: it reads areas, never walks


def get_area_viewer(current_user: dict = Depends(get_platform_user),
                    db: Session = Depends(get_db)) -> AreaViewer:
    groups = current_user.get("cognito_groups", [])
    if "platform_support" in groups and "super_admin" not in groups:
        return AreaViewer(sub=current_user.get("id") or "", writer=None)
    writer = get_writer(current_user, db)
    return AreaViewer(sub=writer.sub, writer=writer)


def _area_out(area: SurveyArea, blocks: list[SurveyAreaBlock], progress: dict) -> AreaOut:
    ps = [progress[b.id] for b in blocks]
    acts = [p.last_activity for p in ps if p.last_activity is not None]
    return AreaOut(
        id=area.id, kind=area.kind, code=area.code, name=area.name, reason=area.reason,
        declared_by_kind=area.declared_by_kind, declared_at=area.declared_at, closed_at=area.closed_at,
        blocks_total=len(blocks),
        blocks_done=sum(p.state == "done" for p in ps),
        blocks_in_progress=sum(p.state == "in_progress" for p in ps),
        doors_total=sum(p.total for p in ps), doors_done=sum(len(p.done) for p in ps),
        last_activity=max(acts) if acts else None,
    )


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return int(2 * 6371000 * asin(sqrt(h)))


@router.get("/areas", response_model=list[AreaOut])
def list_areas(include_closed: bool = Query(False), viewer: AreaViewer = Depends(get_area_viewer),
               db: Session = Depends(get_db)):
    q = db.query(SurveyArea)
    if not include_closed:
        q = q.filter(SurveyArea.closed_at.is_(None))
    out = []
    now = _now()
    for area in q.order_by(SurveyArea.declared_at.desc()).all():
        blocks = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.area_id == area.id).all()
        out.append(_area_out(area, blocks, survey_progress.area_progress(db, blocks, now)))
    return out


@router.post("/areas", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
def declare_area(body: AreaIn, staff: dict = Depends(get_platform_staff), db: Session = Depends(get_db)):
    """D1/D2: the owner or platform support opens an area. Its blocks are fetched
    from the city and snapshotted now; nothing about it is ever edited."""
    if (db.query(SurveyArea.id).filter(SurveyArea.kind == body.kind, SurveyArea.code == body.code,
                                       SurveyArea.closed_at.is_(None)).first()) is not None:
        raise HTTPException(status_code=409, detail="That area is already open.")
    try:
        boundary = survey_blocks.fetch_boundary(body.kind, body.code)
        blocks = survey_blocks.blocks_in_area(boundary)
    except survey_blocks.UnknownBoundary:
        raise HTTPException(status_code=422, detail="The city has no area with that code.")
    except survey_blocks.AreaTooLarge:
        raise HTTPException(status_code=422,
                            detail="That area is too large to walk. Choose a neighbourhood (NTA) instead.")
    except AddressSourceUnavailable:
        raise HTTPException(status_code=503, detail="The city's data is unavailable. Try again shortly.")
    # A block with no borough or no position cannot be claimed or walked from a
    # claim. Counted into the audit rather than dropped silently.
    usable = [b for b in blocks if b.doors and b.borough and b.centre is not None]
    skipped = len(blocks) - len(usable)
    blocks = usable
    if not blocks:
        raise HTTPException(status_code=422, detail="The city lists no addresses in that area.")

    ident = _staff_identity(staff)
    area = SurveyArea(kind=body.kind, code=body.code, name=boundary.name[:120],
                      boundary_dataset=boundary.dataset,
                      address_dataset=settings.socrata_addresspoint_dataset,
                      fetched_at=_now(), reason=body.reason,
                      declared_by=staff.get("id") or "", declared_by_kind=ident["actor_kind"])
    db.add(area)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That area is already open.")
    for b in blocks:
        lat, lng = b.centre
        db.add(SurveyAreaBlock(area_id=area.id, borough=b.borough, block_key=b.block_key,
                               street=b.street, description=b.description[:160], lat=lat, lng=lng,
                               door_snapshot=[{"address": d["address"], "bin": d.get("bin")} for d in b.doors]))
    db.flush()
    write_audit(db, action_type="survey.area.declare", target_table="survey_areas",
                target_id=str(area.id), actor_id=None, company_id=None,
                detail={**ident, "kind": area.kind, "code": area.code, "blocks": len(blocks),
                        "blocks_skipped": skipped, "doors": sum(len(b.doors) for b in blocks)})
    db.commit()
    db.refresh(area)
    rows = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.area_id == area.id).all()
    return _area_out(area, rows, survey_progress.area_progress(db, rows, _now()))


@router.post("/areas/{area_id}/close", response_model=AreaOut)
def close_area(area_id: UUID, staff: dict = Depends(get_platform_staff), db: Session = Depends(get_db)):
    area = db.query(SurveyArea).filter(SurveyArea.id == area_id).first()
    if area is None:
        raise HTTPException(status_code=404, detail="Area not found.")
    if area.closed_at is not None:
        raise HTTPException(status_code=409, detail="This area is already closed.")
    area.closed_at, area.closed_by = _now(), staff.get("id")
    released = 0
    for c in _active_claims(db).filter(SurveyBlockClaim.area_id == area.id):
        c.released_at, c.release_reason = area.closed_at, "area_closed"
        released += 1
    db.flush()
    write_audit(db, action_type="survey.area.close", target_table="survey_areas",
                target_id=str(area.id), actor_id=None, company_id=None,
                detail={**_staff_identity(staff), "claims_released": released})
    db.commit()
    db.refresh(area)
    rows = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.area_id == area.id).all()
    return _area_out(area, rows, survey_progress.area_progress(db, rows, _now()))


@router.get("/areas/{area_id}/blocks", response_model=list[AreaBlockOut])
def area_blocks(area_id: UUID,
                lat: Optional[float] = Query(None, ge=40.4, le=41.0),
                lng: Optional[float] = Query(None, ge=-74.3, le=-73.6),
                viewer: AreaViewer = Depends(get_area_viewer), db: Session = Depends(get_db)):
    """D3: an area's blocks with their state and claim, nearest first when a
    location is given, otherwise in the city's street order."""
    area = db.query(SurveyArea).filter(SurveyArea.id == area_id).first()
    if area is None:
        raise HTTPException(status_code=404, detail="Area not found.")
    blocks = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.area_id == area.id).all()
    progress = survey_progress.area_progress(db, blocks, _now())
    keys = {b.block_key for b in blocks}
    claims = {(c.borough, c.block_key): c for c in _active_claims(db)
              .filter(SurveyBlockClaim.block_key.in_(keys)).all()} if keys else {}
    out = []
    for b in blocks:
        p = progress[b.id]
        c = claims.get((b.borough, b.block_key))
        mine = c is not None and viewer.writer is not None and c.writer_sub == viewer.sub
        out.append(AreaBlockOut(
            id=b.id, borough=b.borough, block_key=b.block_key, street=b.street, description=b.description,
            state=p.state, doors_done=len(p.done), doors_total=p.total,
            reopens_on=(p.completed_at + timedelta(days=REVISIT_DAYS)).date() if p.completed_at else None,
            last_activity=p.last_activity,
            claim=("mine" if mine else "taken") if c is not None else None,
            claim_id=c.id if mine else None,
            distance_m=_distance_m(lat, lng, b.lat, b.lng) if lat is not None and lng is not None else None,
        ))
    if lat is not None and lng is not None:
        out.sort(key=lambda x: x.distance_m or 0)
    else:
        out.sort(key=lambda x: (x.street, x.block_key))
    return out


@router.post("/areas/{area_id}/blocks/{block_id}/claim", response_model=ClaimOut,
             status_code=status.HTTP_201_CREATED)
def claim_block(area_id: UUID, block_id: UUID, writer: Writer = Depends(get_writer),
                db: Session = Depends(get_db)):
    """D3: hold one block for CLAIM_HOURS. One active claim per block across
    every area; at most MAX_ACTIVE_CLAIMS per writer."""
    row = (db.query(SurveyAreaBlock, SurveyArea)
           .join(SurveyArea, SurveyArea.id == SurveyAreaBlock.area_id)
           .filter(SurveyAreaBlock.id == block_id, SurveyAreaBlock.area_id == area_id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Block not found in this area.")
    block, area = row
    if area.closed_at is not None:
        raise HTTPException(status_code=409, detail="This area is closed.")

    _lock_block(db, block.borough, block.block_key)
    held = _active_claims(db).filter(SurveyBlockClaim.borough == block.borough,
                                     SurveyBlockClaim.block_key == block.block_key).first()
    if held is not None:
        raise HTTPException(status_code=409, detail=(
            "You already hold this block." if held.writer_sub == writer.sub
            else "Someone else is walking this block."))
    if _active_claims(db).filter(SurveyBlockClaim.writer_sub == writer.sub).count() >= MAX_ACTIVE_CLAIMS:
        raise HTTPException(status_code=409, detail=(
            f"You can hold {MAX_ACTIVE_CLAIMS} blocks at a time. Finish or release one first."))
    p = survey_progress.progress_for(db, block.borough, block.block_key,
                                     [d["address"] for d in block.door_snapshot], _now())
    if p.state == "done":
        reopens = (p.completed_at + timedelta(days=REVISIT_DAYS)).date() if p.completed_at else None
        raise HTTPException(status_code=409, detail=(
            f"This block is done. It re-opens on {reopens.isoformat()}." if reopens
            else "This block is done."))

    claim = SurveyBlockClaim(area_id=area.id, area_block_id=block.id, borough=block.borough,
                             block_key=block.block_key, writer_sub=writer.sub,
                             claimed_at=_now(), expires_at=_now() + timedelta(hours=CLAIM_HOURS))
    db.add(claim)
    db.flush()
    write_audit(db, action_type="survey.claim.create", target_table="survey_block_claims",
                target_id=str(claim.id), actor_id=None, company_id=None,
                detail={"area_id": str(area.id), "block_key": block.block_key,
                        "writer": "owner" if writer.owner else "contributor"})
    db.commit()
    db.refresh(claim)
    return _claim_out(db, claim)


def _claim_out(db: Session, c: SurveyBlockClaim) -> ClaimOut:
    block = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.id == c.area_block_id).one()
    area = db.query(SurveyArea).filter(SurveyArea.id == c.area_id).one()
    walk = db.query(SurveyWalk).filter(SurveyWalk.id == c.walk_id).first() if c.walk_id else None
    p = survey_progress.progress_for(db, c.borough, c.block_key, [d["address"] for d in block.door_snapshot], _now())
    return ClaimOut(id=c.id, area_id=area.id, area_name=area.name, area_block_id=block.id,
                    street=block.street, description=block.description,
                    claimed_at=c.claimed_at, expires_at=c.expires_at, walk_id=c.walk_id,
                    walk_open=walk is not None and walk.closed_at is None,
                    doors_done=len(p.done), doors_total=p.total)


def _own_claim(db: Session, claim_id: UUID, writer: Writer) -> SurveyBlockClaim:
    c = (db.query(SurveyBlockClaim)
         .filter(SurveyBlockClaim.id == claim_id, SurveyBlockClaim.writer_sub == writer.sub).first())
    if c is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return c


def _in_force(c: SurveyBlockClaim) -> bool:
    return c.released_at is None and survey_progress._aware(c.expires_at) > _now()


@router.get("/claims", response_model=list[ClaimOut])
def my_claims(writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    claims = (_active_claims(db).filter(SurveyBlockClaim.writer_sub == writer.sub)
              .order_by(SurveyBlockClaim.expires_at).all())
    return [_claim_out(db, c) for c in claims]


@router.post("/claims/{claim_id}/release", response_model=ClaimOut)
def release_claim(claim_id: UUID, writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    c = _own_claim(db, claim_id, writer)
    if not _in_force(c):
        raise HTTPException(status_code=409, detail="This claim has already ended.")
    c.released_at, c.release_reason = _now(), "released"
    db.flush()
    write_audit(db, action_type="survey.claim.release", target_table="survey_block_claims",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail={"writer": "owner" if writer.owner else "contributor"})
    db.commit()
    db.refresh(c)
    return _claim_out(db, c)


@router.post("/claims/{claim_id}/walk", response_model=WalkOut, status_code=status.HTTP_201_CREATED)
def start_claimed_walk(claim_id: UUID, body: AttestIn, writer: Writer = Depends(get_writer),
                       db: Session = Depends(get_db)):
    """Start the walk of a claimed block. The city's list is fetched fresh around
    the block's centre, so a door the city added since the area was declared is
    on it (D6)."""
    c = _own_claim(db, claim_id, writer)
    if not _in_force(c):
        raise HTTPException(status_code=409, detail="This claim has ended. Claim the block again.")
    if c.walk_id is not None:
        walk = db.query(SurveyWalk).filter(SurveyWalk.id == c.walk_id).one()
        if walk.closed_at is None:
            raise HTTPException(status_code=409, detail="You already have a walk on this block. Continue it.")
    block = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.id == c.area_block_id).one()
    try:
        nearby = survey_blocks.blocks_near(block.lat, block.lng, survey_blocks.MAX_RADIUS_M)
    except AddressSourceUnavailable:
        raise HTTPException(status_code=503, detail="The city's address list is unavailable. Try again shortly.")
    fresh = next((b for b in nearby if b.block_key == block.block_key
                  and (b.borough or block.borough) == block.borough), None)
    if fresh is None or not fresh.doors:
        raise HTTPException(status_code=422, detail="The city's list no longer has this block.")
    fresh.borough = block.borough
    return _create_walk(db, writer, fresh, area_id=c.area_id, claim=c)


@router.post("/doors/unlock", response_model=UnlockOut)
def unlock_door(body: UnlockIn, writer: Writer = Depends(get_writer), db: Session = Depends(get_db)):
    """D6: the owner re-opens one done door for a correction. The earlier
    observation stays (ADR-504 D5); it just stops locking the door."""
    if not writer.owner:
        raise HTTPException(status_code=403, detail="Only the owner can unlock a door.")
    walk = db.query(SurveyWalk).filter(SurveyWalk.id == body.walk_id).first()
    if walk is None:
        raise HTTPException(status_code=404, detail="Walk not found.")
    if walk.borough is None:
        raise HTTPException(status_code=422, detail="Walks from before survey areas have no lock to undo.")
    if body.address_index >= len(walk.addresses or []):
        raise HTTPException(status_code=422, detail="That door is not on this walk's list.")
    address = walk.addresses[body.address_index]["address"]
    doors = [d["address"] for d in walk.addresses]
    p = survey_progress.progress_for(db, walk.borough, walk.block_key, doors, _now())
    if address not in p.done:
        raise HTTPException(status_code=409, detail="That door isn't locked.")
    if _CODE_WORDS.search(body.reason):
        raise HTTPException(status_code=422, detail="This can't hold access or door codes.")
    u = SurveyDoorUnlock(borough=walk.borough, block_key=walk.block_key, address=address,
                         reason=body.reason.strip(), unlocked_by=writer.sub, unlocked_at=_now())
    db.add(u)
    db.flush()
    # Ids only: the address stays out of the audit (ADR-493 D8).
    write_audit(db, action_type="survey.door.unlock", target_table="survey_door_unlocks",
                target_id=str(u.id), actor_id=None, company_id=None,
                detail={"walk_id": str(walk.id), "writer": "owner"})
    db.commit()
    p = survey_progress.progress_for(db, walk.borough, walk.block_key, doors, _now())
    return UnlockOut(address=address, block_state=p.state)



# ── ADR-545: survey activity, and helping a stuck surveyor ─────────────────────
#
# Platform support (and the owner) can SEE who is surveying and UNSTICK an
# account or a claim. None of this writes a survey record (walks,
# observations): ADR-504 keeps support off the dataset. Every action is
# audited with the caller's real kind (_staff_identity).

class ContributorHealthOut(BaseModel):
    id: UUID
    display_name: str
    email: Optional[str] = None             # ADR-509 D3: visible to platform staff
    cognito_username: Optional[str] = None
    agreement_version: str
    agreement_signed_on: date
    revoked_at: Optional[datetime] = None
    # "never_signed_in" | "active" | "disabled" | "missing" | "unknown"
    account_status: str
    in_surveyor_group: Optional[bool] = None    # None = could not tell
    last_walk_at: Optional[datetime] = None


class ActivityClaimOut(BaseModel):
    id: UUID
    area_name: str
    street: str
    description: str
    holder: str                # contributor name, or "Owner"
    claimed_at: datetime
    expires_at: datetime
    walk_open: bool


class StaffReleaseOut(ActivityClaimOut):
    # ADR-546 D4: whether the holder's notice was actually sent, so the page
    # never claims "emailed" for a send that failed or had no address.
    holder_emailed: bool


class ActivityWalkOut(BaseModel):
    id: UUID
    holder: str
    area_name: Optional[str] = None
    street: str
    started_at: datetime
    last_observation_at: Optional[datetime] = None
    doors_done: int            # observations recorded on this walk
    doors_total: int           # doors on its list


class ActivityOut(BaseModel):
    contributors: list[ContributorHealthOut]
    claims: list[ActivityClaimOut]
    open_walks: list[ActivityWalkOut]


def _account_state(client, username: Optional[str]) -> tuple[str, Optional[bool]]:
    """Cognito's view of a contributor: status, and whether `surveyor` is held."""
    if not username:
        return "unknown", None
    pool = settings.aws_cognito_user_pool_id
    try:
        u = client.admin_get_user(UserPoolId=pool, Username=username)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
            return "missing", False
        return "unknown", None
    except BotoCoreError:
        return "unknown", None
    if not u.get("Enabled", True):
        status_ = "disabled"
    elif u.get("UserStatus") == "FORCE_CHANGE_PASSWORD":
        status_ = "never_signed_in"
    else:
        status_ = "active"
    try:
        groups = client.admin_list_groups_for_user(UserPoolId=pool, Username=username, Limit=60)
        in_group = any(g["GroupName"] == "surveyor" for g in groups.get("Groups", []))
    except (ClientError, BotoCoreError):
        in_group = None
    return status_, in_group


@router.get("/activity", response_model=ActivityOut)
def survey_activity(staff: dict = Depends(get_platform_staff), db: Session = Depends(get_db)):
    """D2 — who is surveying, what they hold, and what is stuck. Status and
    counts only: no observation contents."""
    from sqlalchemy import func as sa_func

    contributors = db.query(SurveyContributor).order_by(SurveyContributor.display_name).all()
    names = {c.cognito_sub: c.display_name for c in contributors}

    def holder(sub: str) -> str:
        return names.get(sub, "Owner")

    last_walk = dict(db.query(SurveyWalk.writer_sub, sa_func.max(SurveyWalk.started_at))
                     .group_by(SurveyWalk.writer_sub).all())

    client = _cognito()
    health = []
    for c in contributors:
        status_, in_group = _account_state(client, c.cognito_username)
        health.append(ContributorHealthOut(
            id=c.id, display_name=c.display_name, email=c.email, cognito_username=c.cognito_username,
            agreement_version=c.agreement_version, agreement_signed_on=c.agreement_signed_on,
            revoked_at=c.revoked_at, account_status=status_, in_surveyor_group=in_group,
            last_walk_at=last_walk.get(c.cognito_sub),
        ))

    claims = []
    for cl in _active_claims(db).order_by(SurveyBlockClaim.expires_at).all():
        block = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.id == cl.area_block_id).one()
        area = db.query(SurveyArea).filter(SurveyArea.id == cl.area_id).one()
        walk = db.query(SurveyWalk).filter(SurveyWalk.id == cl.walk_id).first() if cl.walk_id else None
        claims.append(ActivityClaimOut(
            id=cl.id, area_name=area.name, street=block.street, description=block.description,
            holder=holder(cl.writer_sub), claimed_at=cl.claimed_at, expires_at=cl.expires_at,
            walk_open=walk is not None and walk.closed_at is None,
        ))

    walks = []
    for w in (db.query(SurveyWalk).filter(SurveyWalk.closed_at.is_(None))
              .order_by(SurveyWalk.started_at).all()):
        n, last = (db.query(sa_func.count(SurveyObservation.id), sa_func.max(SurveyObservation.observed_at))
                   .filter(SurveyObservation.walk_id == w.id).one())
        area = db.query(SurveyArea).filter(SurveyArea.id == w.area_id).first() if w.area_id else None
        walks.append(ActivityWalkOut(
            id=w.id, holder=holder(w.writer_sub), area_name=area.name if area else None,
            street=w.street, started_at=w.started_at, last_observation_at=last,
            doors_done=n or 0, doors_total=len(w.addresses or []),
        ))
    return ActivityOut(contributors=health, claims=claims, open_walks=walks)


def _contributor_or_404(db: Session, contributor_id: UUID) -> SurveyContributor:
    c = db.query(SurveyContributor).filter(SurveyContributor.id == contributor_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    if not c.cognito_username:
        raise HTTPException(status_code=409, detail="This contributor has no sign-in account on record.")
    return c


@router.post("/contributors/{contributor_id}/resend", response_model=InviteOut)
def resend_contributor_signin(contributor_id: UUID, staff: dict = Depends(get_platform_staff),
                              db: Session = Depends(get_db)):
    """D3 — a fresh temporary password, emailed. Only while they have never
    signed in: once they have, this would reset a working password."""
    c = _contributor_or_404(db, contributor_id)
    if c.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This contributor is revoked. Re-admit them first.")
    client = _cognito()
    status_, _ = _account_state(client, c.cognito_username)
    if status_ != "never_signed_in":
        raise HTTPException(status_code=409, detail=(
            "They've already signed in, so their password works. If they've forgotten it, "
            "they can use Forgot password on the sign-in page."))
    temp_password = _temp_password()
    try:
        client.admin_set_user_password(UserPoolId=settings.aws_cognito_user_pool_id,
                                       Username=c.cognito_username, Password=temp_password,
                                       Permanent=False)
    except (ClientError, BotoCoreError) as exc:
        logger.error("survey resend: set password failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reset the temporary password.")
    write_audit(db, action_type="survey.contributor.resend", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None, detail=_staff_identity(staff))
    db.commit()
    delivered = True
    try:
        send_credentials_email(to_email=c.email, employee_name=c.display_name,
                               username=c.cognito_username, temp_password=temp_password)
    except Exception as exc:
        logger.error("survey resend: credentials email failed: %s", type(exc).__name__)
        delivered = False
    return InviteOut(contributor=ContributorOut.model_validate(c), email_delivered=delivered,
                     temp_password=None if delivered else temp_password)


@router.post("/contributors/{contributor_id}/restore-access", response_model=ContributorOut)
def restore_contributor_access(contributor_id: UUID, staff: dict = Depends(get_platform_staff),
                               db: Session = Depends(get_db)):
    """D3 — put an ACTIVE contributor back in `surveyor` when the group is missing."""
    c = _contributor_or_404(db, contributor_id)
    if c.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This contributor is revoked. Re-admit them instead.")
    client = _cognito()
    _, in_group = _account_state(client, c.cognito_username)
    if in_group:
        raise HTTPException(status_code=409, detail="They already have surveyor access.")
    try:
        client.admin_add_user_to_group(UserPoolId=settings.aws_cognito_user_pool_id,
                                       Username=c.cognito_username, GroupName="surveyor")
    except (ClientError, BotoCoreError) as exc:
        logger.error("survey restore: group add failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not restore surveyor access.")
    write_audit(db, action_type="survey.contributor.restore_access", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None, detail=_staff_identity(staff))
    db.commit()
    return c


class ReadmitIn(BaseModel):
    """D3 — re-admission is admission: the agreement is signed again (ADR-504 D1)."""
    model_config = ConfigDict(extra="forbid")
    agreement_version: str = Field(min_length=1, max_length=20)
    agreement_signed_on: date
    confirm_agreement_signed: bool

    @model_validator(mode="after")
    def _signed(self):
        if not self.confirm_agreement_signed:
            raise ValueError("Only re-admit someone who has signed the contributor agreement again.")
        if self.agreement_signed_on > date.today():
            raise ValueError("The signing date can't be in the future.")
        return self


@router.post("/contributors/{contributor_id}/readmit", response_model=ContributorOut)
def readmit_contributor(contributor_id: UUID, body: ReadmitIn, staff: dict = Depends(get_platform_staff),
                        db: Session = Depends(get_db)):
    """D3 — only a contributor who was revoked; the exclusion is re-checked."""
    c = _contributor_or_404(db, contributor_id)
    if c.revoked_at is None:
        raise HTTPException(status_code=409, detail="This contributor isn't revoked.")
    _assert_not_excluded(db, c.cognito_sub)
    c.revoked_at = None
    c.agreement_version = body.agreement_version
    c.agreement_signed_on = body.agreement_signed_on
    c.admitted_at = _now()
    c.admitted_by = (staff.get("id") or "")[:64] or None
    db.flush()
    write_audit(db, action_type="survey.contributor.readmit", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail={**_staff_identity(staff), "agreement_version": body.agreement_version})
    db.commit()
    db.refresh(c)
    try:
        _cognito().admin_add_user_to_group(UserPoolId=settings.aws_cognito_user_pool_id,
                                           Username=c.cognito_username, GroupName="surveyor")
    except (ClientError, BotoCoreError) as exc:
        # The row is what get_writer reads; Survey activity will show the
        # missing group, and Restore access fixes it.
        logger.warning("survey readmit: group add failed: %s", type(exc).__name__)
    return c


# ── ADR-550 D2: support resets a surveyor's two-factor, by surveyor ID ─────

# Not _CODE_WORDS: that keeps building access codes out of survey records, and
# it refuses "lost their phone and cannot get codes" -- the most likely reason
# anyone writes here. The risk in THIS text is a real one-time code or a
# password pasted in, so refuse digit runs that could be one.
_SECRET_LIKE = re.compile(r"\d{4,}")
_STAFF_GROUPS = {"super_admin", "platform_support"}


class ResetMfaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=200)


class ResetMfaOut(BaseModel):
    contributor_id: UUID
    signed_out: bool
    factor_cleared: bool
    devices_forgotten: int
    surveyor_emailed: bool


def _surveyor_only_account(client, db: Session, c: SurveyContributor) -> str:
    """The Cognito username behind contributor `c`, IF it is only a surveyor.

    Resolved by the SUB on the row, which never changes -- not the stored
    username or a typed name. Refuses (409) anything that is more than a
    surveyor: a staff group, or a tenant Employee behind the same sub. That is
    what keeps support's reset from ever reaching a staff or tenant account.
    """
    try:
        sub = str(UUID(c.cognito_sub))           # validated: safe inside the filter
    except ValueError:
        raise HTTPException(status_code=409, detail="This contributor's account ID isn't valid.")
    pool = settings.aws_cognito_user_pool_id
    try:
        users = client.list_users(UserPoolId=pool, Filter=f'sub = "{sub}"', Limit=1).get("Users", [])
        if not users:
            raise HTTPException(status_code=409, detail="This contributor has no sign-in account.")
        username = users[0]["Username"]
        groups = {g["GroupName"] for g in client.admin_list_groups_for_user(
            UserPoolId=pool, Username=username, Limit=60).get("Groups", [])}
    except (ClientError, BotoCoreError) as exc:
        logger.error("survey mfa reset: could not read the account: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not look up the account. Try again.")
    if "surveyor" not in groups:
        raise HTTPException(status_code=409, detail="This account doesn't hold surveyor access.")
    if groups & _STAFF_GROUPS:
        raise HTTPException(status_code=409, detail=(
            "This account is also platform staff. Only a super admin can reset it, from Platform staff."))
    if db.query(Employee.id).filter(Employee.cognito_sub == sub).first() is not None:
        raise HTTPException(status_code=409, detail=(
            "This account belongs to a company employee. Their own admin resets it."))
    return username


@router.post("/contributors/{contributor_id}/reset-mfa", response_model=ResetMfaOut)
def reset_contributor_mfa(contributor_id: UUID, body: ResetMfaIn,
                          staff: dict = Depends(get_platform_staff),
                          db: Session = Depends(get_db)):
    """ADR-550 D2 — clear a locked-out surveyor's two-factor, by surveyor ID.

    Support's way to rescue someone who lost their phone, without a super
    admin. Bounded like ADR-545's actions: it can only reach an account that is
    a surveyor and nothing more (_surveyor_only_account). Ends every session --
    at Cognito and here -- restarts the 24-hour setup window (ADR-466 D1),
    audits against the surveyor ID, and emails the surveyor.
    """
    if _SECRET_LIKE.search(body.reason):
        raise HTTPException(status_code=422, detail="A reason can't include codes or long numbers.")
    reason, _flags = scrub_note(body.reason.strip())
    reason = reason or ""
    if len(reason) < 10:
        raise HTTPException(status_code=422, detail="Give a reason of at least 10 characters.")

    c = db.query(SurveyContributor).filter(SurveyContributor.id == contributor_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Contributor not found.")
    if c.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This contributor is revoked. Re-admit them first.")

    username = _surveyor_only_account(_cognito(), db, c)
    result = mfa_containment.contain(username=username, pool_id=settings.aws_cognito_user_pool_id,
                                     region=settings.aws_region, clear_factor=True)
    account_security.mark_sessions_ended(db, c.cognito_sub)
    db.flush()
    write_audit(db, action_type="survey.contributor.mfa_reset", target_table="survey_contributors",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail={**_staff_identity(staff), "reason": reason,
                        "signed_out": result.signed_out, "factor_cleared": result.factor_cleared,
                        "devices_forgotten": result.devices_forgotten, "errors": result.errors})
    db.commit()

    emailed = False
    if c.email:
        try:
            send_surveyor_mfa_reset_notice(to_email=c.email, name=c.display_name, reason=reason,
                                           account_ref=str(c.id))
            emailed = True
        except Exception as exc:
            logger.warning("survey mfa reset: notice failed: %s", type(exc).__name__)

    if not result.fully_contained:
        raise HTTPException(status_code=502, detail="The reset did not fully complete. Please try again.")
    return ResetMfaOut(contributor_id=c.id, signed_out=result.signed_out,
                       factor_cleared=result.factor_cleared,
                       devices_forgotten=result.devices_forgotten, surveyor_emailed=emailed)


class StaffReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=200)


@router.post("/claims/{claim_id}/staff-release", response_model=StaffReleaseOut)
def staff_release_claim(claim_id: UUID, body: StaffReleaseIn, staff: dict = Depends(get_platform_staff),
                        db: Session = Depends(get_db)):
    """D4 — free a block someone is holding. The walk and its observations are
    untouched; the holder is emailed the reason."""
    # The reason is emailed and audited, so it gets the note's two guards (D4):
    # refuse anything that reads as an access code, then scrub what's left.
    if _CODE_WORDS.search(body.reason):
        raise HTTPException(status_code=422, detail="A reason can't mention codes, PINs or passwords.")
    reason, _flags = scrub_note(body.reason.strip())
    reason = reason or ""
    if len(reason) < 10:
        raise HTTPException(status_code=422, detail="Give a reason of at least 10 characters.")
    c = db.query(SurveyBlockClaim).filter(SurveyBlockClaim.id == claim_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    if not _in_force(c):
        raise HTTPException(status_code=409, detail="This claim has already ended.")
    c.released_at, c.release_reason = _now(), "staff_released"
    db.flush()
    write_audit(db, action_type="survey.claim.staff_release", target_table="survey_block_claims",
                target_id=str(c.id), actor_id=None, company_id=None,
                detail={**_staff_identity(staff), "reason": reason})
    db.commit()
    db.refresh(c)

    block = db.query(SurveyAreaBlock).filter(SurveyAreaBlock.id == c.area_block_id).one()
    area = db.query(SurveyArea).filter(SurveyArea.id == c.area_id).one()
    holder = db.query(SurveyContributor).filter(SurveyContributor.cognito_sub == c.writer_sub).first()
    emailed = False
    if holder is not None and holder.email:
        try:
            send_claim_released_notice(to_email=holder.email, name=holder.display_name,
                                       block=block.description, area=area.name,
                                       reason=reason, account_ref=str(holder.id))
            emailed = True
        except Exception as exc:
            logger.warning("survey staff release: notice failed: %s", type(exc).__name__)
    walk = db.query(SurveyWalk).filter(SurveyWalk.id == c.walk_id).first() if c.walk_id else None
    return StaffReleaseOut(id=c.id, area_name=area.name, street=block.street, description=block.description,
                           holder=holder.display_name if holder else "Owner", claimed_at=c.claimed_at,
                           expires_at=c.expires_at, walk_open=walk is not None and walk.closed_at is None,
                           holder_emailed=emailed)
