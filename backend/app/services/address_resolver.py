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

READ-ONLY (ADR-581)
-------------------
This module never writes PlaceType. ADR-316 D3's write-through stored every
GeoClient answer for a tenant's address in the owner's store, which made
PlaceType a list of tenants' delivery addresses (ADR-580). The write-back is
deleted; a pinned test (test_adr581_no_tenant_writes_placetype) refuses its
return.
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
    failures: int = 0

    def as_dict(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
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

    # ADR-581 D1: READ-ONLY. This used to write the answer back into PlaceType
    # (ADR-316 D3, "write-through"), which put every tenant's package and tote
    # addresses into the owner's store. PlaceType is never written from a
    # tenant path; the cache warms only from the owner's own seed (ADR-580).
    return geo

