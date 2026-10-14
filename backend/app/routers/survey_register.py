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
    DAY_STATUS, DELIVERY_MODES, DELIVERY_POINTS, MAX_DELIVERY_POINTS, SOURCES, TRISTATE,
    SurveyContributor, SurveyDeliveryPoint, SurveyObservation, SurveyReceivesFor, SurveyWalk,
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
    recorded: list[int]          # indexes already observed on this walk


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

    # D8: each door's city block, the streets that block faces, and its
    # same-block neighbours, snapshotted with the list (best effort).
    doors = survey_blocks.enrich_doors(block.doors)
    walk = SurveyWalk(
        writer_sub=writer.sub, block_key=block.block_key, street=block.street,
        addresses=doors, source_dataset=settings.socrata_addresspoint_dataset,
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
