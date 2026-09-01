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
import urllib.parse
import urllib.request
import json
from dataclasses import dataclass
from typing import Iterator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_SODA_HOST = "https://data.cityofnewyork.us/resource"
_PAGE = 1000
# A zone larger than this is a configuration mistake, not a big zone: Manhattan
# entire is ~180k addresses. Bounding the walk keeps a bad polygon from pulling
# the whole city.
_MAX_RECORDS = 50_000
_TIMEOUT = 45


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

    The form is otherwise exactly what `derive_block_key` expects, so no mapping
    table is needed — verified end-to-end against the real parser.
    """
    return re.sub(r"\s+", " ", (raw or "")).strip()


def _fetch_page(polygon: str, offset: int) -> list[dict]:
    params = {
        "$select": "house_number,full_street_name,boroughcode,bin,the_geom",
        "$where": f"within_polygon(the_geom, '{polygon}')",
        "$order": "addresspointid",   # stable key — pagination is meaningless without it
        "$limit": str(_PAGE),
        "$offset": str(offset),
    }
    url = f"{_SODA_HOST}/{settings.socrata_addresspoint_dataset}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    # D8: a rate-limit identifier for public data, not an authorisation grant.
    if settings.socrata_app_token:
        req.add_header("X-App-Token", settings.socrata_app_token)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.load(resp)
    except Exception as exc:
        # No str(exc) beyond the log: the URL carries the polygon and the header
        # carries the token, and neither belongs in a response body.
        logger.warning("address_inventory: SODA page failed offset=%s: %s",
                       offset, type(exc).__name__)
        raise AddressSourceUnavailable("address source unavailable") from exc


def enumerate_zone_addresses(bounds: dict) -> Iterator[EnumeratedAddress]:
    """Yield every AddressPoint record inside `bounds`.

    Raises AddressSourceUnavailable if the upstream cannot be reached. Yields
    nothing for a zone with no usable polygon.
    """
    from app.services.derive_block_key import derive_block_key

    polygon = polygon_from_bounds(bounds)
    if polygon is None:
        logger.info("address_inventory: zone has no usable polygon; nothing to enumerate")
        return

    seen: set[str] = set()
    offset = 0
    while offset < _MAX_RECORDS:
        rows = _fetch_page(polygon, offset)
        if not rows:
            return
        for row in rows:
            house = (row.get("house_number") or "").strip()
            street = _normalise_street(row.get("full_street_name"))
            if not house or not street:
                continue
            address = f"{house} {street}"
            if address in seen:
                continue
            seen.add(address)

            # `tba` labels an UnparseableAddress for reporting and carries no
            # package meaning; workforce mode has no TBA to supply.
            parsed = derive_block_key(address, tba="")
            block_key = getattr(parsed, "block_key", None)

            lat = lng = None
            geom = row.get("the_geom") or {}
            coords = geom.get("coordinates")
            if isinstance(coords, list) and len(coords) == 2:
                lng, lat = float(coords[0]), float(coords[1])

            yield EnumeratedAddress(
                normalised_address=address,
                block_key=block_key,
                lat=lat,
                lng=lng,
                bin=(row.get("bin") or None),
                borough_code=(row.get("boroughcode") or None),
            )
        if len(rows) < _PAGE:
            return
        offset += _PAGE
    logger.warning("address_inventory: hit the %s-record ceiling; zone may be too large",
                   _MAX_RECORDS)


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

    # Materialised: the list is walked twice — once for tenant rows, once to
    # seed PlaceType below. An iterator would be empty on the second pass.
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

    # ADR-314 — seed PlaceType with what AddressPoint already gives us.
    #
    # bin/lat/lng are 3 of the 11 geometry columns and arrive FREE with the
    # enumeration; the other 8 (bbl, zip, segment_id, corner_code, structures,
    # frontages, geo_grc) need a GeoClient call per address and stay deferred
    # (ADR-303 D9). Seeding now means the identity anchor exists from day one
    # and a second tenant in the same zone inherits it without any enrichment
    # pass having run.
    #
    # Best-effort: PlaceType is a shared resource and a failure to seed it must
    # not fail a tenant's bootstrap.
    seeded = 0
    try:
        from app.services.place_geometry import upsert_building_geometry
        seeded = upsert_building_geometry(db, [
            {"normalised_address": a.normalised_address,
             "block_key": a.block_key,
             "bin": a.bin, "lat": a.lat, "lng": a.lng}
            for a in addresses if a.block_key
        ])
    except Exception:
        logger.warning("address_inventory: PlaceType seed failed; tenant rows are unaffected",
                       exc_info=False)

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_unparseable": skipped_unparseable,
        "bin_backfilled": backfilled,
        "placetype_seeded": seeded,
    }
