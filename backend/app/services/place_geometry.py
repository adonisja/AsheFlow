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
    seen: set[str] = set()
    for r in rows:
        addr = _clean(r.get("normalised_address"))
        bk = _clean(r.get("block_key"))
        if not addr or not bk:
            continue
        # ON CONFLICT cannot fire twice for the same key in one statement.
        if addr in seen:
            continue
        seen.add(addr)
        row = {k: r.get(k) for k in _GEOMETRY_COLUMNS if k != "geo_enriched_at"}
        row.update({
            "normalised_address": addr,
            "block_key": bk,
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
        index_elements=["normalised_address"],
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


def pending_enrichment(db: Session, limit: int) -> list[tuple[str, str]]:
    """Addresses that have never been through GeoClient, oldest first (ADR-315 D2).

    Lives here rather than in the task because this module owns PlaceType's
    geometry tier — the ADR-237 boundary test flagged the task importing
    `BuildingProfileLibrary` directly, correctly: a second module naming the
    model is how ownership erodes.

    Returns `(normalised_address, block_key)` rather than ORM rows so the caller
    cannot mutate them behind this module's back.
    """
    rows = (
        db.query(BuildingProfileLibrary.normalised_address,
                 BuildingProfileLibrary.block_key)
        .filter(BuildingProfileLibrary.geo_enriched_at.is_(None))
        .order_by(BuildingProfileLibrary.created_at.asc())
        .limit(limit)
        .all()
    )
    return [(a, b) for a, b in rows]


def pending_enrichment_count(db: Session) -> int:
    """How many rows still await GeoClient."""
    return (
        db.query(BuildingProfileLibrary)
        .filter(BuildingProfileLibrary.geo_enriched_at.is_(None))
        .count()
    )
