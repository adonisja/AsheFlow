"""Enumerate the addresses inside a company's operating zone (ADR-303).

The segment map self-seeds from packages (`enrich_manifest`), which is full-mode.
A workforce tenant has no manifest, so nothing ever populates its address
inventory and ADR-238's accepted segment uses have no data to run on.

This enumerates from NYC Open Data's AddressPoint dataset, filtered SERVER-SIDE
by the zone polygon, so the transfer is proportional to the zone rather than the
city (967k records exist; a ~1km Midtown box returns ~1k).

Scope (ADR-303 D9): this pass builds the INVENTORY only and makes zero GeoClient
calls. `block_key` is derived locally. Segment resolution (D3) and span
derivation (D4) both cost roughly one GeoClient call per address and are
deferred until that cost is measured on a real zone.

Best-effort throughout, matching `segment_map.py`'s stance: GeoClient being down
must degrade routing, never fail a sort. Nothing downstream requires an
inventory — that is the state every tenant is in today.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterator, Optional


logger = logging.getLogger(__name__)

# A zone larger than this is a configuration mistake, not a big zone: Manhattan
# entire is ~180k addresses. Bounding the walk keeps a bad polygon from pulling
# the whole city.
_MAX_RECORDS = 50_000


@dataclass(frozen=True)
class EnumeratedAddress:
    """One AddressPoint record, normalised for BuildingProfile."""
    normalised_address: str
    block_key: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    bin: Optional[str]
    borough_code: Optional[str]


class AddressSourceUnavailable(RuntimeError):
    """The upstream dataset could not be reached or refused the query."""


def polygon_from_bounds(bounds: dict) -> Optional[str]:
    """Render a GeoJSON Polygon as the WKT that `within_polygon()` expects.

    Returns None for anything that is not a usable ring — a zone with no bounds
    is a zone we cannot enumerate, not an error to raise.
    """
    try:
        if bounds.get("type") != "Polygon":
            return None
        ring = bounds["coordinates"][0]
        if len(ring) < 4:
            return None
        pts = ", ".join(f"{float(lng)} {float(lat)}" for lng, lat in ring)
        return f"POLYGON(({pts}))"
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _normalise_street(raw: str) -> str:
    """AddressPoint pads street names ('W  55 ST'); collapse to single spaces.
    Used by the owner's survey (survey_blocks), which reads AddressPoint itself."""
    return re.sub(r"\s+", " ", (raw or "")).strip()


def ring_from_bounds(bounds: dict) -> Optional[list]:
    """The zone's outer ring as (lng, lat) pairs, or None if unusable."""
    try:
        if bounds.get("type") != "Polygon":
            return None
        ring = [(float(lng), float(lat)) for lng, lat in bounds["coordinates"][0]]
        return ring if len(ring) >= 4 else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def enumerate_zone_addresses(bounds: dict) -> Iterator[EnumeratedAddress]:
    """Every PlaceType door inside the zone (ADR-584 D5).

    Was a Socrata AddressPoint walk run by the tenant's request. PlaceType now
    holds the whole city's AddressPoint (ADR-583), so the zone's doors are a
    READ of it; nothing is written to PlaceType (ADR-581).

    Raises AddressSourceUnavailable when PlaceType doesn't answer: the degrade
    guard would otherwise read an outage as "this zone has no addresses".
    """
    from app.database import PlaceTypeSession
    from app.services import door_resolver, place_geometry

    ring = ring_from_bounds(bounds)
    if ring is None:
        logger.info("address_inventory: zone has no usable polygon; nothing to enumerate")
        return
    pt = PlaceTypeSession()
    try:
        if not door_resolver._zip_map(pt):
            raise AddressSourceUnavailable("placetype unavailable")
        doors = place_geometry.doors_in_polygon(pt, ring, limit=_MAX_RECORDS)
    finally:
        pt.close()
    if len(doors) >= _MAX_RECORDS:
        logger.warning("address_inventory: hit the %s-door ceiling; zone may be too large", _MAX_RECORDS)
    for d in doors:
        yield EnumeratedAddress(normalised_address=d["address"], block_key=d["block_key"],
                                lat=d["lat"], lng=d["lng"], bin=d["bin"], borough_code=d["borough"])


# ── Persistence (ADR-303 D2) ─────────────────────────────────────────────────

# A bootstrapped row knows WHERE a building is, not what it is like inside.
# building_type is NOT NULL, so the honest value is an explicit "unknown"
# rather than a plausible guess: inventing "walkup" would make a machine-
# enriched row assert an observation nobody made, which is the ADR-301 failure
# (a label claiming knowledge the code does not have).
#
# Safe to introduce, verified before use:
#   - no Literal/Enum constraint on building_type in any schema
#   - no DB CHECK constraint on the column
#   - route_sort reads WORKLOAD_class, not building_type, via
#     _WORKLOAD_WEIGHTS.get(cls, (1.0, 1.0)) — an unseen value already falls
#     back to the neutral baseline
#   - the web UI switches on building_type_STATUS, not building_type
BOOTSTRAP_BUILDING_TYPE = "unknown"
# 'standard' is _WORKLOAD_WEIGHTS' (1.0, 1.0) baseline — the neutral effect on
# the effort score, which is what an unobserved building should have.
BOOTSTRAP_WORKLOAD_CLASS = "standard"
BOOTSTRAP_SUBMITTED_BY_NAME = "Zone bootstrap"


def persist_zone_inventory(db, company_id, addresses) -> dict:
    """Upsert enumerated addresses into BuildingProfile. Returns a summary.

    Bootstrapped rows are distinguishable from crew-submitted ones by
    `submitted_by IS NULL` (ADR-303 D2): a machine-enriched address and a
    walker's observation carry different authority, and later work —
    verification, promotion to the library — must not treat a bootstrap row as
    though a human vouched for it.

    An address a human HAS already submitted is left untouched. The bootstrap
    supplies what is missing; it never overwrites an observation.
    """
    from app.models.building_profile import BuildingProfile

    # Materialised: callers may pass an iterator, and the count below and the
    # loop both need the whole list.
    addresses = list(addresses)
    created = skipped_existing = skipped_unparseable = 0
    existing_rows = {
        r.normalised_address: r
        for r in db.query(BuildingProfile)
        .filter(BuildingProfile.company_id == company_id).all()
    }
    existing = set(existing_rows)
    backfilled = 0

    for a in addresses:
        if not a.block_key:
            # block_key is NOT NULL and is the routing key; a row without one
            # would be inert. Counted, not silently dropped.
            skipped_unparseable += 1
            continue
        if a.normalised_address in existing:
            skipped_existing += 1
            # A row created before BIN was persisted (or before AddressPoint had
            # one) keeps a null forever otherwise: this path never updates, so
            # the gap would only close if someone deleted the row. Backfill the
            # identity anchor and nothing else — everything else on a tenant row
            # is either a human's observation or already correct.
            if a.bin:
                row = existing_rows.get(a.normalised_address)
                if row is not None and not row.bin:
                    row.bin = a.bin
                    backfilled += 1
            continue

        db.add(BuildingProfile(
            company_id         = company_id,
            normalised_address = a.normalised_address,
            block_key          = a.block_key,
            # ADR-314 D1 — the building identity, available HERE rather than
            # only after GeoClient enrichment. AddressPoint carries `bin`
            # directly and we were already selecting it, then dropping it.
            #
            # Verified before relying on it: across a 937-address zone the
            # AddressPoint bin null rate is 0%, and on a random 20-address
            # sample AddressPoint and GeoClient agreed on every single BIN
            # (20 agree / 0 differ / 0 missing). So the identity anchor does not
            # have to wait for a rate-limited per-address call.
            bin                = a.bin,
            # The ADDRESS is resolved — we have its coordinates and its block
            # key. That is what this column tracks; it says nothing about
            # whether the building has been observed.
            address_status     = "resolved",
            building_type      = BOOTSTRAP_BUILDING_TYPE,
            workload_class     = BOOTSTRAP_WORKLOAD_CLASS,
            lat                = a.lat,
            lng                = a.lng,
            # submitted_by stays NULL — the marker of a bootstrap row. The name
            # column is NOT NULL, so it carries the provenance instead.
            submitted_by_name  = BOOTSTRAP_SUBMITTED_BY_NAME,
        ))
        existing.add(a.normalised_address)
        created += 1

    # ADR-581 D2: no PlaceType seed from here. Which addresses this writes is
    # chosen by the TENANT's zone, so seeding PlaceType from it made the owner's
    # store a record of where a tenant delivers (ADR-580). PlaceType is filled
    # only by the owner's citywide seed (ADR-583). The tenant's own inventory
    # above is unchanged.

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_unparseable": skipped_unparseable,
        "bin_backfilled": backfilled,
    }
