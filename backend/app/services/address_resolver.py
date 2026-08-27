"""Resolve an address from PlaceType first, GeoClient second (ADR-316).

THE PROBLEM THIS FIXES
----------------------
ADR-303 enumerates a zone's addresses, ADR-314 gives PlaceType a geometry tier,
ADR-315 fills it from GeoClient overnight — and then every caller resolved a
package address by calling GeoClient anyway. Six call sites, not one of them
checking a local table: no lru_cache, no per-run dict, nothing. The same address
went over the network every time it appeared, across sorts, across days, and
twice within one manifest.

The data was preloaded and nothing read it.

WHY THE ANSWER IS A JOIN
------------------------
`GeoClientResult` has 14 fields. PlaceType splits them by what they describe:
the building row holds identity and position, and its SEGMENT holds topology —
cross streets, LION nodes, and the blockface endpoints. Both are needed to
answer a routing caller, so a hit is a join, not a single-row read.

`geo_message` is the one field deliberately not cached: it describes a single
lookup's outcome ("ADDRESS NUMBER OUT OF RANGE"), and replaying a stored message
against a different request would misreport what just happened.

WHAT COUNTS AS A HIT
--------------------
Not "a row exists". A bootstrap-only row carries bin/lat/lng from AddressPoint
and no topology at all — enough to place a pin, not enough to route. Serving it
would produce blank CSV columns nobody could explain, so it is a MISS and the
caller reaches GeoClient (ADR-316 D2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class ResolverStats:
    """Per-run counters (ADR-316 D4).

    A cache with no hit-rate telemetry is one nobody will notice has stopped
    working: an address-format drift, a normalisation change or a non-NYC tenant
    sends the hit rate to zero while every call still succeeds.
    """
    hits: int = 0
    misses: int = 0
    written_back: int = 0
    failures: int = 0

    def as_dict(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "written_back": self.written_back,
            "failures": self.failures,
            "hit_rate": round(self.hits / total, 3) if total else None,
        }


def _from_placetype(db: Session, address: str):
    """Assemble a GeoClientResult from PlaceType, or None on a miss.

    Reads through `place_geometry`, which owns this tier (ADR-237 D1) — the
    boundary test rejects a second module naming the models.
    """
    from app.tasks.enrich_manifest import GeoClientResult
    from app.services.place_geometry import enriched_building_with_segment

    row = enriched_building_with_segment(db, address)
    if row is None:
        return None
    building, segment = row

    # Topology lives on the segment. Without it the answer cannot serve a
    # routing caller, so an enriched building whose segment was never persisted
    # is a miss rather than a partial answer (D2).
    if segment is None:
        return None

    return GeoClientResult(
        normalised_address = building.normalised_address,
        lat                = building.lat,
        lng                = building.lng,
        first_cross_street = segment.first_cross_street,
        second_cross_street= segment.second_cross_street,
        segment_id         = building.segment_id or segment.segment_id,
        from_lion_node_id  = segment.from_lion_node_id,
        to_lion_node_id    = segment.to_lion_node_id,
        x_low_address_end  = segment.x_low_address_end,
        y_low_address_end  = segment.y_low_address_end,
        x_high_address_end = segment.x_high_address_end,
        y_high_address_end = segment.y_high_address_end,
        geo_grc            = building.geo_grc,
        # Not cached on purpose — see the module docstring.
        geo_message        = None,
    )


def resolve_address(
    db: Session,
    address: str,
    borough: str = "manhattan",
    *,
    stats: Optional[ResolverStats] = None,
    write_back: bool = True,
):
    """PlaceType first, GeoClient second. Returns GeoClientResult or None.

    Signature-compatible with `_geoclient_normalise` plus `db`, so the six call
    sites converge here rather than each carrying its own strategy — which is
    how the missing cache went unnoticed in the first place.

    Degrades exactly as today: a GeoClient failure returns None, which every
    existing caller already handles.
    """
    cached = _from_placetype(db, address)
    if cached is not None:
        if stats:
            stats.hits += 1
        return cached

    if stats:
        stats.misses += 1

    from app.tasks.enrich_manifest import _geoclient_normalise
    geo = _geoclient_normalise(address, borough=borough)
    if geo is None:
        if stats:
            stats.failures += 1
        return None

    # D3 — write-through, so the cache warms from real traffic as well as from
    # the nightly pass. Without it a cache only ever holds what a batch job
    # reached, which is stale for exactly the addresses that are new.
    if write_back:
        try:
            _write_back(db, geo)
            if stats:
                stats.written_back += 1
        except Exception:
            # Never fail a caller because the cache could not be warmed. No
            # exception text: the address is PII-adjacent and the URL carries it.
            logger.warning("address_resolver: write-back failed for one address")

    return geo


def _write_back(db: Session, geo) -> None:
    """Persist a GeoClient answer into PlaceType.

    Composes the owning writers rather than issuing SQL: `upsert_building_geometry`
    COALESCEs (ADR-314 D1c) so this cannot erase what the enrichment pass
    supplied, and `upsert_segments` owns `street_segments` (ADR-237 D2).
    """
    from app.services.place_geometry import upsert_building_geometry
    from app.services.segment_map import upsert_segments
    from app.services.derive_block_key import derive_block_key

    parsed = derive_block_key(geo.normalised_address, tba="")
    block_key = getattr(parsed, "block_key", None)
    if not block_key:
        # block_key is NOT NULL on the library and is the routing key; a row
        # without one would be inert.
        return

    upsert_building_geometry(db, [{
        "normalised_address": geo.normalised_address,
        "block_key": block_key,
        "lat": geo.lat,
        "lng": geo.lng,
        "segment_id": geo.segment_id,
        "geo_grc": geo.geo_grc,
    }], mark_enriched=True)

    if geo.segment_id:
        upsert_segments(db, [{
            "segment_id":          geo.segment_id,
            "from_lion_node_id":   geo.from_lion_node_id,
            "to_lion_node_id":     geo.to_lion_node_id,
            "block_key":           block_key,
            "first_cross_street":  geo.first_cross_street,
            "second_cross_street": geo.second_cross_street,
            "x_low_address_end":   geo.x_low_address_end,
            "y_low_address_end":   geo.y_low_address_end,
            "x_high_address_end":  geo.x_high_address_end,
            "y_high_address_end":  geo.y_high_address_end,
        }])
