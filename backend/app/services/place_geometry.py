"""PlaceType's geometry tier: ground truth about buildings (ADR-314).

WHY THIS IS NOT IN `library/client.py`
--------------------------------------
`client.py` is read-only and says so: "WRITES ARE NOT HERE." ADR-237 D5 settled
that AsheFlow never writes the Library directly — it PUSHES nominations through
the promotion gate, and the Library owner accepts or rejects them.

That rule is about INTELLIGENCE: a tenant's observation becoming a shared claim
needs a gate, because the claim carries authority.

Geometry is a different kind of fact with a different source. "This building is
at 40.75, -73.99 and its BIN is 1015862" comes from the City of New York, not
from a tenant, and needs no cross-tenant agreement to be true. It already has an
accepted precedent in this codebase: `segment_map.upsert_segments` writes
`street_segments` — PlaceType's other dataset — directly, and ADR-237 D2 kept
that mechanism while moving its ownership.

So this module follows `upsert_segments`, not `promote_to_library`: idempotent,
ON CONFLICT DO UPDATE keyed on the public identifier, no tenant data in, counts
out. `client.py` stays read-only and the nomination rule stays intact.

THE DISJOINT-COLUMN INVARIANT (ADR-314 D0b)
-------------------------------------------
Two write doors into one table are safe only while their column sets do not
overlap. This module writes GEOMETRY columns and must never write
`building_type`, `workload_class`, `operational_note`, hours, or any status
except the `geometry_only` placement below. A machine-enriched row has 230
fields of city data and still knows nothing about what a building is like to
deliver to.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import reads_placetype
from app.library.client import _degrades_to
from app.models.building_profile_library import BuildingProfileLibrary

logger = logging.getLogger(__name__)

# A row that has geometry but no verified intelligence. NOT "active".
#
# Verified why this matters: client.all_active() filters on nothing but
# library_status == "active", and run_sort._get_workload_dicts builds its
# workload dict straight from that result. A geometry row marked active would
# enter routing carrying a NULL workload_class, read as verified-but-empty.
# A distinct status makes the existing one-line filter correct with no change
# to it.
GEOMETRY_ONLY = "geometry_only"

# `building_type` and `workload_class` are NOT NULL on this table, so a
# geometry-only row cannot simply omit them — found by inserting against real
# Postgres, which the structural tests could not see.
#
# Reuse ADR-303's sentinels rather than relaxing the constraints: "unknown" says
# plainly that nobody has observed this building, and "standard" is
# _WORKLOAD_WEIGHTS' (1.0, 1.0) baseline, the neutral effect on an effort score.
# Making the columns nullable would weaken them for the PROMOTED rows, where
# NOT NULL is doing real work — a promoted row without a building type is a
# broken promotion.
#
# These are written on INSERT only. They are never in the conflict update set,
# so an enrichment pass over a promoted row cannot overwrite a real type with
# "unknown" (D0b).
UNOBSERVED_BUILDING_TYPE = "unknown"
UNOBSERVED_WORKLOAD_CLASS = "standard"

# Columns this module owns. Anything outside this set belongs to the promotion
# gate and must not be touched here (D0b).
_GEOMETRY_COLUMNS = (
    "bin", "bbl", "zip_code", "lat", "lng", "segment_id",
    "corner_code", "structures_on_lot", "street_frontages",
    "geo_grc", "geo_enriched_at",
)


def _as_int(v) -> Optional[int]:
    """GeoClient returns zero-padded strings ('0003'). Blank means absent."""
    try:
        s = (v or "").strip()
        return int(s) if s else None
    except (TypeError, ValueError):
        return None


def _clean(v) -> Optional[str]:
    s = (v or "").strip()
    return s or None


def geometry_from_geoclient(resp: dict) -> dict:
    """Project a GeoClient address response onto the geometry columns.

    Deliberately NOT the whole response. Measured: the full payload is 7,532
    bytes per address — 36 MB for one 4,786-address zone — against 497 bytes for
    this subset. The discarded bulk (dcpZoningMap, atomicPolygon,
    cooperativeIdNumber) has no consumer in this codebase.
    """
    lat, lng = resp.get("latitude"), resp.get("longitude")
    return {
        "bin":               _clean(resp.get("buildingIdentificationNumber")),
        "bbl":               _clean(resp.get("bbl")),
        "zip_code":          _clean(resp.get("zipCode")),
        "lat":               float(lat) if lat is not None else None,
        "lng":               float(lng) if lng is not None else None,
        "segment_id":        _clean(resp.get("segmentIdentifier")),
        "corner_code":       _clean(resp.get("cornerCode")),
        "structures_on_lot": _as_int(resp.get("numberOfExistingStructuresOnLot")),
        "street_frontages":  _as_int(resp.get("numberOfStreetFrontagesOfLot")),
        "geo_grc":           _clean(resp.get("geosupportReturnCode")),
    }


def upsert_building_geometry(db: Session, rows: Iterable[dict],
                             *, mark_enriched: bool = False) -> int:
    """Idempotently persist building geometry into PlaceType. Returns rows written.

    Each row needs `normalised_address` and `block_key` (both NOT NULL on the
    table); the geometry keys are optional.

    ON CONFLICT DO UPDATE keyed on normalised_address — the table's unique
    constraint — so concurrent bootstraps from different companies upserting the
    same public building cannot raise and cannot duplicate. That mirrors
    `upsert_segments`, which solved the same race for topology.

    `library_status` is set to `geometry_only` ONLY on insert. An existing row
    that a human already promoted keeps its status and its intelligence: the
    update touches geometry columns and nothing else (D0b).
    """
    now = datetime.now(timezone.utc)
    payload = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        addr = _clean(r.get("normalised_address"))
        bk = _clean(r.get("block_key"))
        boro = _clean(r.get("borough"))
        # ADR-583 D5: a door is (borough, address); a row without a borough
        # cannot be placed and is not written.
        if not addr or not bk or not boro:
            continue
        # ON CONFLICT cannot fire twice for the same key in one statement.
        if (boro, addr) in seen:
            continue
        seen.add((boro, addr))
        row = {k: r.get(k) for k in _GEOMETRY_COLUMNS if k != "geo_enriched_at"}
        row.update({
            "normalised_address": addr,
            "block_key": bk,
            "borough": boro,
            # `geo_enriched_at` means "GeoClient has run for this address",
            # NOT "this row was written". The bootstrap seed writes bin/lat/lng
            # from AddressPoint and must leave it NULL, or the enrichment pass
            # sees zero pending rows and silently never runs — which is exactly
            # what happened the first time this was wired up (ADR-315 D2).
            "geo_enriched_at": (now if mark_enriched else None),
            # Insert-only placement (see the constants above). Absent from the
            # conflict update set, so a promoted row keeps its real values.
            "library_status": GEOMETRY_ONLY,
            "building_type": UNOBSERVED_BUILDING_TYPE,
            "workload_class": UNOBSERVED_WORKLOAD_CLASS,
        })
        payload.append(row)

    if not payload:
        return 0

    stmt = pg_insert(BuildingProfileLibrary).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["borough", "normalised_address"],
        # library_status is absent on purpose: a promoted row must not be
        # demoted to geometry_only by a later enrichment pass.
        #
        # COALESCE(excluded, stored) rather than straight assignment: the two
        # sources are UNEVEN. AddressPoint supplies bin/lat/lng only; GeoClient
        # supplies all eleven. A plain overwrite meant a bootstrap re-run wiped
        # every column enrichment had filled — verified against real Postgres,
        # where a re-run with a null bin cleared bin, bbl, zip, segment_id AND
        # structures_on_lot in one statement.
        #
        # So a null NEVER erases a known value, whichever source produced it:
        # AddressPoint fills what GeoClient has not reached, GeoClient fills
        # what AddressPoint could not supply, and neither can undo the other.
        # `geo_enriched_at` is excluded from the rule — it is a timestamp of the
        # last write, not a fact to preserve.
        set_={
            c: (getattr(stmt.excluded, c) if c == "geo_enriched_at"
                else func.coalesce(getattr(stmt.excluded, c),
                                   getattr(BuildingProfileLibrary, c)))
            for c in _GEOMETRY_COLUMNS
        },
    )
    db.execute(stmt)
    return len(payload)


# NOTE: there is no segment writer here on purpose. `segment_map` owns every
# read and write of `street_segments` (ADR-237 D2), and `upsert_segments`
# already accepts optional keys — so the span goes through it rather than
# through a second writer that the boundary test would rightly flag.
#
# Use `span_from_geoclient()` below to build the dict, then hand it to
# `segment_map.upsert_segments`.


def span_from_geoclient(resp: dict) -> dict:
    """Project a GeoClient response onto the segment-span columns."""
    return {
        "segment_id":          _clean(resp.get("segmentIdentifier")),
        "low_house_number":    _clean(resp.get("lowHouseNumberOfBlockfaceSortFormat")),
        "high_house_number":   _clean(resp.get("highHouseNumberOfBlockfaceSortFormat")),
        # GeoClient v2 returns lowCrossStreetName1 / highCrossStreetName1; the
        # older firstCrossStreetName* fields are ABSENT from v2 responses.
        # `enrich_manifest` already learned this and reads them in this order —
        # a draft here had the order reversed and would have written NULL cross
        # streets forever, silently, since the field simply is not in the
        # payload. Same order, same fallback, so both paths agree.
        "first_cross_street":  _clean(resp.get("lowCrossStreetName1")
                                      or resp.get("firstCrossStreetNameNormalized")),
        "second_cross_street": _clean(resp.get("highCrossStreetName1")
                                      or resp.get("secondCrossStreetNameNormalized")),
        # ADR-316 — the blockface endpoints, in NY State Plane feet. Segment
        # geometry (verified: identical across three addresses on segment
        # 0297696), and the last GeoClientResult fields PlaceType could not
        # answer. Without them every routing caller had to miss the cache.
        "x_low_address_end":   _as_int(resp.get("xCoordinateLowAddressEnd")),
        "y_low_address_end":   _as_int(resp.get("yCoordinateLowAddressEnd")),
        "x_high_address_end":  _as_int(resp.get("xCoordinateHighAddressEnd")),
        "y_high_address_end":  _as_int(resp.get("yCoordinateHighAddressEnd")),
    }


def pending_enrichment(db: Session, limit: int, after_id=None) -> list[tuple]:
    """Doors that have never been through GeoClient (ADR-315 D2), for the
    owner's seed (ADR-583 D6). Keyset-paged by id, so a 22-hour pass resumes
    where it stopped and never re-reads a page.

    Lives here because this module owns PlaceType's geometry tier: the ADR-237
    boundary test rejects a second module naming the model.

    Returns `(id, normalised_address, block_key, borough)` tuples rather than
    ORM rows, so the caller cannot mutate them behind this module's back.
    """
    q = (db.query(BuildingProfileLibrary.id, BuildingProfileLibrary.normalised_address,
                  BuildingProfileLibrary.block_key, BuildingProfileLibrary.borough)
         .filter(BuildingProfileLibrary.geo_enriched_at.is_(None),
                 BuildingProfileLibrary.borough.isnot(None)))
    if after_id is not None:
        q = q.filter(BuildingProfileLibrary.id > after_id)
    return [tuple(r) for r in q.order_by(BuildingProfileLibrary.id).limit(limit).all()]


def door_count(db: Session) -> int:
    """Distinct doors in PlaceType, for the seed's report (ADR-583)."""
    return db.query(BuildingProfileLibrary).count()


def pending_enrichment_count(db: Session) -> int:
    """How many rows still await GeoClient."""
    return (
        db.query(BuildingProfileLibrary)
        .filter(BuildingProfileLibrary.geo_enriched_at.is_(None))
        .count()
    )


def create_indexes(bind) -> list[str]:
    """Add any index the model declares that PlaceType's table lacks (ADR-584).
    `create_table` skips an existing table, so a later index needs this."""
    made = []
    for ix in BuildingProfileLibrary.__table__.indexes:
        ix.create(bind, checkfirst=True)
        made.append(ix.name)
    return made


def create_table(bind) -> str:
    """Create the building table in PlaceType's own database (ADR-583 D6),
    from the model, so the two can't drift. Owner seed only."""
    BuildingProfileLibrary.__table__.create(bind, checkfirst=True)
    return BuildingProfileLibrary.__tablename__


@reads_placetype
def enriched_building_with_segment(db: Session, normalised_address: str):
    """An ENRICHED building row plus its segment, or None (ADR-316 D2).

    The join is the point: identity and position live on the building row,
    topology lives on the segment, and a routing caller needs both. Returning
    the building alone would answer half the question and produce blank columns
    downstream.

    `geo_enriched_at IS NULL` is a miss, not a partial hit — a bootstrap-only
    row carries bin/lat/lng from AddressPoint and no topology at all.

    Lives here rather than in the resolver because this module owns PlaceType's
    geometry tier (ADR-237 D1); the boundary test rejects a second module naming
    the models.
    """
    import re
    from app.services.derive_block_key import derive_block_key
    from app.services.segment_map import by_segment_id

    # The lookup CANNOT key on the raw string. AddressPoint and GeoClient use
    # different vocabularies for the same door — "350 5 AVE" vs "350 5 AVENUE",
    # "2 W 33 ST" vs "2 WEST 33 STREET" — and a cache keyed on one form never
    # serves the other. Measured: 0 of 4 sample addresses matched, so the first
    # version of this cache could not hit at all.
    #
    # `derive_block_key` already collapses both vocabularies to one key (both
    # forms above yield 5_Ave_300 / W_33_St_0), so (house number, block_key) is
    # a join that survives whichever source wrote the row.
    building = (
        db.query(BuildingProfileLibrary)
        .filter(
            BuildingProfileLibrary.normalised_address == normalised_address,
            BuildingProfileLibrary.geo_enriched_at.isnot(None),
        )
        .first()
    )
    if building is None:
        m = re.match(r"\s*(\d+)\s", normalised_address or "")
        parsed = derive_block_key(normalised_address, tba="")
        block_key = getattr(parsed, "block_key", None)
        if not (m and block_key):
            return None
        house = m.group(1)
        candidates = (
            db.query(BuildingProfileLibrary)
            .filter(
                BuildingProfileLibrary.block_key == block_key,
                BuildingProfileLibrary.geo_enriched_at.isnot(None),
            )
            .all()
        )
        building = next(
            (c for c in candidates
             if re.match(r"\s*(\d+)\s", c.normalised_address or "")
             and re.match(r"\s*(\d+)\s", c.normalised_address).group(1) == house),
            None,
        )
        if building is None:
            return None

    return building, by_segment_id(db, building.segment_id)


# ── ADR-584: door reads for the tenant resolver and the picker ───────────────

def _house(address: str) -> str:
    """The standard is "{HOUSE} {STREET}" and a house carries no space (ADR-582)."""
    return (address or "").partition(" ")[0]


@_degrades_to(None)
@reads_placetype
def door_with_segment(db: Session, borough: Optional[str], address: str):
    """(building, segment or None) for a door, or None. ADR-584 D1.

    A door that EXISTS is a hit, enriched or not: AddressPoint's base row
    already places it (BIN, lat/lng, block key). Topology comes with it once the
    seed's GeoClient pass has reached it. Unlike `enriched_building_with_segment`,
    which treated a base-only row as a miss for the GeoClient-backed resolver.

    With a borough: (borough, address), else the same house on the same block
    in that borough. Without one: the address only if it is unique citywide.
    """
    from app.services.derive_block_key import derive_block_key
    from app.services.segment_map import by_segment_id

    q = db.query(BuildingProfileLibrary).filter(
        BuildingProfileLibrary.normalised_address == address)
    if borough:
        building = q.filter(BuildingProfileLibrary.borough == borough).first()
    else:
        rows = q.limit(2).all()
        building = rows[0] if len(rows) == 1 else None

    if building is None and borough:
        block_key = getattr(derive_block_key(address, tba=""), "block_key", None)
        house = _house(address)
        if block_key and house:
            building = next(
                (c for c in db.query(BuildingProfileLibrary).filter(
                    BuildingProfileLibrary.borough == borough,
                    BuildingProfileLibrary.block_key == block_key).all()
                 if _house(c.normalised_address) == house),
                None)
    if building is None:
        return None
    segment = by_segment_id(db, building.segment_id) if building.segment_id else None
    return building, segment


def _box(lat: float, lng: float, metres: float):
    import math
    dlat = metres / 111_320.0
    dlng = metres / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def _metres(lat1, lng1, lat2, lng2) -> float:
    import math
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6_371_000.0 * math.hypot(x, y)


@_degrades_to(list)
@reads_placetype
def doors_near(db: Session, lat: float, lng: float, *, radius_m: float = 150.0,
               limit: int = 10, street: Optional[str] = None) -> list[dict]:
    """The nearest doors to a point, for the tenant's picker (ADR-584 D4).

    Bounded on both axes (radius and count) so it can never dump an area
    (ADR-580 D6). Returns only what a picker shows: the door, its borough, its
    distance and its position.
    """
    lat0, lat1, lng0, lng1 = _box(lat, lng, radius_m)
    q = db.query(BuildingProfileLibrary.normalised_address, BuildingProfileLibrary.borough,
                 BuildingProfileLibrary.lat, BuildingProfileLibrary.lng).filter(
        BuildingProfileLibrary.lat.between(lat0, lat1),
        BuildingProfileLibrary.lng.between(lng0, lng1),
        BuildingProfileLibrary.borough.isnot(None))
    if street:
        q = q.filter(BuildingProfileLibrary.normalised_address.ilike(f"% {street.strip()}%"))
    found = []
    for address, borough, dlat, dlng in q.limit(2000).all():
        d = _metres(lat, lng, dlat, dlng)
        if d <= radius_m:
            found.append({"address": address, "borough": borough,
                          "distance_m": round(d, 1), "lat": dlat, "lng": dlng})
    found.sort(key=lambda r: r["distance_m"])
    return found[:limit]


@_degrades_to(dict)
@reads_placetype
def zip_boroughs(db: Session) -> dict[str, str]:
    """ZIP → borough code, from PlaceType's own doors (ADR-584 D2). A ZIP that
    spans two boroughs is left out, so it can't decide anything."""
    rows = (db.query(BuildingProfileLibrary.zip_code, BuildingProfileLibrary.borough)
            .filter(BuildingProfileLibrary.zip_code.isnot(None),
                    BuildingProfileLibrary.borough.isnot(None))
            .distinct().all())
    seen: dict[str, set] = {}
    for z, b in rows:
        seen.setdefault(z, set()).add(b)
    return {z: next(iter(bs)) for z, bs in seen.items() if len(bs) == 1}


def _house_number(house: str) -> Optional[int]:
    """The numeric part a person compares: 455A → 455, 123-45 → 12345."""
    import re
    digits = re.sub(r"[^0-9]", "", house or "")
    return int(digits) if digits else None


@_degrades_to(list)
@reads_placetype
def doors_on_block(db: Session, borough: Optional[str], address: str, *, limit: int = 10) -> list[dict]:
    """Real doors on the same street near a typed address (ADR-584 D4), for a
    picker with no location to search from: a captain entering a tote's
    address at the truck is standing at the staging point, not the door.

    Same block key and its two neighbours (±100 for a hundred-block, ±1 for a
    hyphenated Queens block), closest house number first. Indexed on (borough,
    block_key); bounded to `limit` doors. Without a borough, all five.
    """
    import re
    from app.services.derive_block_key import derive_block_key

    block_key = getattr(derive_block_key(address, tba=""), "block_key", None)
    m = re.match(r"^(.*)_(\d+)$", block_key or "")
    if not m:
        return []
    stem, n = m.group(1), int(m.group(2))
    house = _house(address)
    step = 1 if "-" in house else 100
    keys = [f"{stem}_{k}" for k in (n - step, n, n + step) if k >= 0]
    target = _house_number(house)

    q = db.query(BuildingProfileLibrary.normalised_address, BuildingProfileLibrary.borough,
                 BuildingProfileLibrary.lat, BuildingProfileLibrary.lng).filter(
        BuildingProfileLibrary.block_key.in_(keys))
    q = q.filter(BuildingProfileLibrary.borough == borough) if borough else \
        q.filter(BuildingProfileLibrary.borough.in_(["1", "2", "3", "4", "5"]))
    rows = q.limit(500).all()

    def gap(addr):
        h = _house_number(_house(addr))
        return abs(h - target) if (h is not None and target is not None) else 10**9
    rows.sort(key=lambda r: (gap(r[0]), r[0]))
    return [{"address": a, "borough": b, "lat": la, "lng": ln, "house_gap": gap(a)}
            for a, b, la, ln in rows[:limit]]
