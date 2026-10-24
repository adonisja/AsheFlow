"""Resolve a customer's address to a PlaceType door, and nothing else (ADR-584).

No GeoClient, ever: a customer's address does not leave AsheFlow (ADR-580 D4).
No write to PlaceType (ADR-581). Logs carry counts only (ADR-587).

    resolve_door(db, address, lat=None, lng=None, default_borough=None) -> Door | Miss

A Door carries what routing reads: position, identity and, once the city seed
has reached it, its segment's topology. A Miss is not an error: the caller holds
the address for the tenant to pick a door or drop a pin (ADR-584 D4).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ZIP = re.compile(r"\b(1[0-1]\d{3})(?:-\d{4})?\b")     # NYC ZIPs are 100xx–114xx
BOROUGH_WITHIN_M = 200.0

# The ZIP map changes only when the seed re-runs. Measured on 60,651 doors: the
# first resolve took 269 ms building it, the next ones 2–14 ms. Rebuilding it per
# call over the city's ~946k doors would cost every package that much again.
_ZIP_TTL_S = 6 * 3600
_zip_cache: dict = {"map": None, "at": 0.0}


def _zip_map(db: Session) -> dict:
    import time
    from app.services import place_geometry
    now = time.monotonic()
    if _zip_cache["map"] is None or now - _zip_cache["at"] > _ZIP_TTL_S:
        fresh = place_geometry.zip_boroughs(db)
        if not fresh:                       # unreachable or empty: don't cache a blank
            return _zip_cache["map"] or {}
        _zip_cache.update(map=fresh, at=now)
    return _zip_cache["map"]


@dataclass(frozen=True)
class Door:
    borough: str
    address: str
    block_key: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    bin: Optional[str] = None
    bbl: Optional[str] = None
    zip_code: Optional[str] = None
    segment_id: Optional[str] = None
    first_cross_street: Optional[str] = None
    second_cross_street: Optional[str] = None
    from_lion_node_id: Optional[str] = None
    to_lion_node_id: Optional[str] = None
    x_low_address_end: Optional[int] = None
    y_low_address_end: Optional[int] = None
    x_high_address_end: Optional[int] = None
    y_high_address_end: Optional[int] = None


@dataclass(frozen=True)
class Miss:
    """Why no door matched, plus what the picker needs to start from."""
    reason: str                       # "no_address" | "no_borough_match" | "not_in_placetype"
    address: Optional[str] = None     # the canonical form tried, never the raw text
    borough: Optional[str] = None
    near: list = field(default_factory=list)


def company_borough(db: Session, company_id) -> Optional[str]:
    """The company's configured borough as a code, read once by the caller from
    the TENANT session (ADR-584 D2 step 3). Replaces `_company_borough` and the
    `Company.geoclient_borough` read (a column that lives on CompanyConfig)."""
    from app.models.company import CompanyConfig
    from app.services.door_key import borough_code
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    return borough_code(cfg.geoclient_borough) if cfg and cfg.geoclient_borough else None


def borough_for(db: Session, text: str, lat: Optional[float], lng: Optional[float],
                default_borough: Optional[str] = None) -> Optional[str]:
    """ADR-584 D2: a ZIP in the text, else the nearest door within 200 m, else
    the caller's default (the company's configured borough), else None — and
    then only an address unique across the city matches.

    `db` may be a PlaceType session: nothing here reads a tenant table."""
    from app.services import place_geometry

    m = _ZIP.search(text or "")
    if m:
        b = _zip_map(db).get(m.group(1))
        if b:
            return b
    if lat is not None and lng is not None:
        near = place_geometry.doors_near(db, lat, lng, radius_m=BOROUGH_WITHIN_M, limit=1)
        if near:
            return near[0]["borough"]
    return default_borough


def resolve_door(db: Session, address: str, *, lat: Optional[float] = None,
                 lng: Optional[float] = None, default_borough: Optional[str] = None):
    """A Door, or a Miss for the tenant to pick (ADR-584 D1)."""
    from app.services import place_geometry
    from app.services.door_key import canonical_address

    borough = borough_for(db, address, lat, lng, default_borough)
    canonical = canonical_address(address or "", borough)
    if not canonical:
        return Miss("no_address", borough=borough)

    row = place_geometry.door_with_segment(db, borough, canonical)
    if row is None:
        # With a location, the doors around it; without one (a captain typing
        # at the truck), the real doors on the same street and block.
        near = (place_geometry.doors_near(db, lat, lng) if lat is not None and lng is not None
                else place_geometry.doors_on_block(db, borough, canonical))
        return Miss("not_in_placetype" if borough else "no_borough_match",
                    address=canonical, borough=borough, near=near)

    return _door(row)


def door_from_pick(db: Session, borough: str, address: str):
    """The door a tenant picked from the list: must exist in PlaceType."""
    from app.services import place_geometry
    row = place_geometry.door_with_segment(db, borough, address)
    return None if row is None else _door(row)


def _door(row) -> Door:
    b, seg = row
    return Door(
        borough=b.borough, address=b.normalised_address, block_key=b.block_key,
        lat=b.lat, lng=b.lng, bin=b.bin, bbl=b.bbl, zip_code=b.zip_code,
        segment_id=b.segment_id,
        first_cross_street=getattr(seg, "first_cross_street", None),
        second_cross_street=getattr(seg, "second_cross_street", None),
        from_lion_node_id=getattr(seg, "from_lion_node_id", None),
        to_lion_node_id=getattr(seg, "to_lion_node_id", None),
        x_low_address_end=getattr(seg, "x_low_address_end", None),
        y_low_address_end=getattr(seg, "y_low_address_end", None),
        x_high_address_end=getattr(seg, "x_high_address_end", None),
        y_high_address_end=getattr(seg, "y_high_address_end", None),
    )


# ── ADR-584 D4: what a manifest package carries after a door, a miss or a pin ─

PIN_SNAP_M = 30.0


def door_fields(door: Door) -> dict:
    """The day-manifest fields for a resolved package (same keys enrichment wrote)."""
    return {
        "door_status": "resolved", "borough": door.borough,
        "normalised_address": door.address, "block_key": door.block_key,
        "lat": door.lat, "lng": door.lng,
        "segment_id": door.segment_id,
        "first_cross_street": door.first_cross_street,
        "second_cross_street": door.second_cross_street,
        "from_lion_node_id": door.from_lion_node_id, "to_lion_node_id": door.to_lion_node_id,
        "x_low_address_end": door.x_low_address_end, "y_low_address_end": door.y_low_address_end,
        "x_high_address_end": door.x_high_address_end, "y_high_address_end": door.y_high_address_end,
        # A door the seed's GeoClient pass hasn't reached yet: placed, not yet topological.
        "geo_warning": None if door.segment_id else "no_segment_topology",
        "geocode_reason": None,
    }


def _parser_block(address: Optional[str]) -> Optional[str]:
    from app.services.derive_block_key import derive_block_key
    return getattr(derive_block_key(address, tba=""), "block_key", None) if address else None


def miss_fields(miss: Miss) -> dict:
    """An unresolved package: held for the tenant (ADR-584 D4). It keeps Amazon's
    lat/lng (not overwritten here) and a parser block key, for the picker."""
    return {
        "door_status": "unresolved", "borough": miss.borough,
        "normalised_address": None, "block_key": _parser_block(miss.address),
        "segment_id": None, "first_cross_street": None, "second_cross_street": None,
        "from_lion_node_id": None, "to_lion_node_id": None,
        "x_low_address_end": None, "y_low_address_end": None,
        "x_high_address_end": None, "y_high_address_end": None,
        "geo_warning": None, "geocode_reason": miss.reason,
    }


def pin_fields(db: Session, lat: float, lng: float, address_hint: Optional[str]) -> dict:
    """A tenant's map pin. The nearest door within 30 m if there is one, else the
    pin stands alone: its position, a parser block key, no topology. Either way
    the package is no longer held, so one typo can't hold a station's sort."""
    from app.services import place_geometry
    near = place_geometry.doors_near(db, lat, lng, radius_m=PIN_SNAP_M, limit=1)
    if near:
        door = door_from_pick(db, near[0]["borough"], near[0]["address"])
        if door is not None:
            return {**door_fields(door), "door_status": "pinned"}
    from app.services.door_key import canonical_address
    return {
        **miss_fields(Miss("pinned")), "door_status": "pinned", "lat": lat, "lng": lng,
        "block_key": _parser_block(canonical_address(address_hint or "")),
        "geo_warning": "pinned_without_door", "geocode_reason": None,
    }


HELD = frozenset({"unresolved"})


def is_held(pkg: dict) -> bool:
    """A package the sort must wait on. Packages written before ADR-584 carry no
    door_status and are not held (their day's manifest predates the rule)."""
    return pkg.get("door_status") in HELD


def needs_attention(pkg: dict) -> bool:
    """For counts and the "failed only" view: held (ADR-584), or, in a manifest
    written before ADR-584 (no door_status), no block key as it always meant."""
    if "door_status" in pkg:
        return is_held(pkg)
    return pkg.get("block_key") is None
