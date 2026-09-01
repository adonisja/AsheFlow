"""Fill PlaceType's geometry tier from GeoClient (ADR-315).

The bootstrap (ADR-303) enumerates a zone from AddressPoint and gets three of
PlaceType's eleven geometry columns free: `bin`, `lat`, `lng`. The other eight —
bbl, zip_code, segment_id, corner_code, structures_on_lot, street_frontages,
geo_grc, plus the segment span on `street_segments` — need one GeoClient call
per address.

WHY THIS IS A BACKGROUND PASS AND NOT PART OF THE BOOTSTRAP
-----------------------------------------------------------
Measured against the live API before designing around it, which ADR-303 D9
insisted on after the address-count estimate came in 5x low:

    workers=1   2.98/s  -> 4,786 addresses = 26.8 min
    workers=4  12.10/s  -> 4,786 addresses =  6.6 min
    workers=8  19.06/s  -> 4,786 addresses =  4.2 min   (0 errors at any level)

Minutes, not hours — so this is an ordinary job. Four workers rather than eight
because the scarce resource is not our time, it is the City's API quota, shared
with `enrich_manifest` on every full-mode sort (ADR-315 D1).

Nothing downstream fails without enrichment, so it runs nightly rather than on
demand and the bootstrap stays synchronous and GeoClient-free.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# ADR-315 D1 — fixed, not tuned. A knob nobody has a number for gets set wrong.
_WORKERS = 4
# ADR-315 D4 — worst-case duration is bounded by the batch, not by whatever a
# tenant defined as its operating area.
_BATCH = 2000


def _enrich_one(address: str, borough: str = "manhattan") -> dict | None:
    """Resolve one address and return the FULL GeoClient response.

    Not `_geoclient_normalise`: that returns a `GeoClientResult` dataclass which
    keeps 14 fields and drops the ones ADR-314 needs — `bbl`, `zipCode`,
    `numberOfExistingStructuresOnLot`, `numberOfStreetFrontagesOfLot`,
    `cornerCode`. A first draft called it and read a `.raw` attribute that does
    not exist, which would have enriched nothing while stamping every row as a
    failure.

    The address handling IS reused, deliberately. `strip_address_noise` removes
    unit/suite/floor text that GeoClient cannot match — its own comment records
    that omitting it "silently failed ~90% of geocodes" — and
    `_parse_house_and_street` splits the same way `block_key` derivation does,
    so both paths agree on what an address is.
    """
    import requests
    from app.core.config import settings
    from app.tasks.enrich_manifest import (
        _GEOCLIENT_BASE, _parse_house_and_street, strip_address_noise,
    )

    if not settings.geoclient_app_key:
        return None
    parsed = _parse_house_and_street(strip_address_noise(address))
    if parsed is None:
        return None
    house, street = parsed
    try:
        resp = requests.get(
            f"{_GEOCLIENT_BASE}/address.json",
            params={"houseNumber": house, "street": street, "borough": borough},
            headers={"Ocp-Apim-Subscription-Key": settings.geoclient_app_key},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json().get("address") or None
    except Exception:
        # No exception text: the URL carries the address and the header carries
        # the API key, and neither belongs in a log (Dimension 6).
        logger.warning("enrich_geometry: GeoClient call failed for one address")
        return None


@celery_app.task(name="app.tasks.enrich_geometry.enrich_place_geometry")
def enrich_place_geometry() -> dict:
    """Enrich PlaceType rows that have never been enriched. Idempotent.

    Resumes on `geo_enriched_at IS NULL`, oldest first (D2), so a pass killed
    partway continues rather than restarting, a completed pass re-run is a
    no-op, and a large zone cannot starve a smaller one added later.
    """
    from app.services.place_geometry import (
        geometry_from_geoclient, pending_enrichment, pending_enrichment_count,
        span_from_geoclient, upsert_building_geometry,
    )
    from app.services.segment_map import upsert_segments

    db = SessionLocal()
    try:
        # Through the owning module, not the model: place_geometry owns
        # PlaceType's geometry tier (ADR-237 D1, enforced by the boundary test).
        rows = pending_enrichment(db, _BATCH)
        if not rows:
            return {"processed": 0, "enriched": 0, "failed": 0, "remaining": 0}

        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            results = list(ex.map(lambda r: _enrich_one(r[0]), rows))

        now = datetime.now(timezone.utc)
        geometry: list[dict] = []
        spans: list[dict] = []
        failed = 0

        for (addr, block_key), res in zip(rows, results):
            if res is None:
                # D3 — stamp the failure and move on. `geo_enriched_at` is set
                # here too, on purpose: without it a permanently unresolvable
                # address is retried on every future run and the pass never
                # converges.
                failed += 1
                geometry.append({
                    "normalised_address": addr, "block_key": block_key,
                    "geo_grc": "ERR",
                })
                continue

            g = geometry_from_geoclient(res)
            g.update({"normalised_address": addr, "block_key": block_key})
            geometry.append(g)

            s = span_from_geoclient(res)
            if s.get("segment_id"):
                spans.append(s)

        # D5 — compose the existing writers. upsert_building_geometry COALESCEs
        # (ADR-314 D1c) so a null from this pass cannot erase what the bootstrap
        # supplied, and upsert_segments owns street_segments (ADR-237 D2).
        written = upsert_building_geometry(db, geometry, mark_enriched=True)
        if spans:
            upsert_segments(db, spans)
        db.commit()

        remaining = pending_enrichment_count(db)
        logger.info(
            "enrich_geometry: processed=%d enriched=%d failed=%d remaining=%d",
            len(rows), written - failed, failed, remaining,
        )
        return {
            "processed": len(rows),
            "enriched": written - failed,
            "failed": failed,
            "remaining": remaining,
        }
    finally:
        db.close()
