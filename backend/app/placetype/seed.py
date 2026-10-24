"""The city seed: PlaceType from public data, written only by the owner (ADR-583 D6).

Run as its own process, with the WRITER role, never from the API or Celery:

    PLACETYPE_WRITER_URL=postgresql://placetype_writer:...@postgres:5432/placetype \\
        python -m app.placetype.seed schema addresspoint geoclient nodes

Every stage is idempotent and resumable:
- `schema`       creates the two PlaceType tables from the ORM models (no drift);
- `addresspoint` all 967,871 NYC addresses, per borough, in the address
                 standard (ADR-582), with BIN, lat/lng, ZIP and block key;
- `geoclient`    every row with geo_enriched_at IS NULL, at <= 12/s (about 22h):
                 geometry onto the building, the span onto its segment;
- `nodes`        LION nodes for segments that lack them (blockface lookups).
                 One pass: a lookup can return a neighbouring segment, so
                 some rows never fill and a re-run repeats them.

The street lexicon (ADR-582) is refreshed locally, not here, because it is a
committed file: `python scripts/build_street_lexicon.py`, then commit it.

Logs carry counts only, never an address (ADR-587 D2).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("placetype.seed")

_SODA = "https://data.cityofnewyork.us/resource"
_GEOCLIENT = "https://api.nyc.gov/geoclient/v2"
_PAGE = 50_000
_BATCH = 500
BOROUGH_NAMES = {"1": "manhattan", "2": "bronx", "3": "brooklyn", "4": "queens", "5": "staten island"}


# ── connection ──────────────────────────────────────────────────────────────

def writer_session() -> Session:
    """The writer role's session. Refuses to run without PLACETYPE_WRITER_URL,
    and refuses the app database: the seed never writes a tenant database."""
    url = os.getenv("PLACETYPE_WRITER_URL")
    if not url:
        raise SystemExit("PLACETYPE_WRITER_URL is not set: the seed runs only with the writer role (ADR-583 D2).")
    if url == settings.database_url:
        raise SystemExit("PLACETYPE_WRITER_URL is the app database: the seed writes PlaceType only.")
    return sessionmaker(bind=create_engine(url, pool_pre_ping=True), autoflush=False)()


# ── stage: schema ───────────────────────────────────────────────────────────

def stage_schema(db: Session) -> dict:
    from app.services import place_geometry, segment_map
    bind = db.get_bind()
    return {"tables": [place_geometry.create_table(bind), segment_map.create_table(bind)]}


# ── stage: addresspoint ─────────────────────────────────────────────────────

def _soda_page(borough: str, offset: int) -> list[dict]:
    params = {
        "$select": "house_number,full_street_name,boroughcode,bin,zipcode,the_geom",
        "$where": f"boroughcode='{borough}'",
        "$order": "addresspointid",
        "$limit": str(_PAGE),
        "$offset": str(offset),
    }
    req = urllib.request.Request(
        f"{_SODA}/{settings.socrata_addresspoint_dataset}.json?" + urllib.parse.urlencode(params))
    if settings.socrata_app_token:
        req.add_header("X-App-Token", settings.socrata_app_token)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:       # noqa: BLE001 — retried, then raised
            logger.warning("addresspoint page failed borough=%s offset=%s attempt=%s: %s",
                           borough, offset, attempt + 1, type(exc).__name__)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"AddressPoint unavailable for borough {borough} at offset {offset}")


def addresspoint_rows(raw: list[dict]) -> Iterator[dict]:
    """AddressPoint records → PlaceType rows in the standard. Pure, for tests."""
    from app.services.derive_block_key import derive_block_key
    from app.services.door_key import canonical_address

    for r in raw:
        house = (r.get("house_number") or "").strip()
        street = " ".join((r.get("full_street_name") or "").split())
        boro = (r.get("boroughcode") or "").strip()
        if not house or not street or boro not in BOROUGH_NAMES:
            continue
        address = canonical_address(f"{house} {street}", boro)
        if not address:
            continue
        parsed = derive_block_key(address, tba="")
        block_key = getattr(parsed, "block_key", None)
        if not block_key:
            continue     # NOT NULL on the table; a named place without a block waits for ADR-584
        lat = lng = None
        coords = (r.get("the_geom") or {}).get("coordinates")
        if isinstance(coords, list) and len(coords) == 2:
            lng, lat = float(coords[0]), float(coords[1])
        yield {
            "normalised_address": address, "block_key": block_key, "borough": boro,
            "bin": (r.get("bin") or None), "zip_code": (r.get("zipcode") or None),
            "lat": lat, "lng": lng,
        }


def stage_addresspoint(db: Session, boroughs=tuple(BOROUGH_NAMES)) -> dict:
    from app.services.place_geometry import upsert_building_geometry
    # `submitted` counts rows sent; AddressPoint has several points for some
    # doors, so `doors` (distinct, after the upserts) is the number to check.
    counts = {"read": 0, "submitted": 0, "skipped": 0}
    for boro in boroughs:
        offset = 0
        while True:
            raw = _soda_page(boro, offset)
            if not raw:
                break
            rows = list(addresspoint_rows(raw))
            counts["read"] += len(raw)
            counts["skipped"] += len(raw) - len(rows)
            for i in range(0, len(rows), _BATCH):
                counts["submitted"] += upsert_building_geometry(db, rows[i:i + _BATCH])
                db.commit()
            logger.info("addresspoint borough=%s offset=%s %s", boro, offset, counts)
            if len(raw) < _PAGE:
                break
            offset += _PAGE
    from app.services.place_geometry import door_count
    counts["doors"] = door_count(db)
    return counts


# ── stage: geoclient ────────────────────────────────────────────────────────

class _Pace:
    """At most `rate` calls per second across threads."""
    def __init__(self, rate: float):
        self.gap, self.lock, self.next = 1.0 / rate, threading.Lock(), time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if self.next > now:
                time.sleep(self.next - now)
            self.next = max(now, self.next) + self.gap


def geoclient_address(house: str, street: str, borough_code: str) -> Optional[dict]:
    """GeoClient v2 /address for one door, or None on a miss. Retries 429/5xx."""
    import requests
    for attempt in range(5):
        try:
            resp = requests.get(
                f"{_GEOCLIENT}/address.json",
                params={"houseNumber": house, "street": street,
                        "borough": BOROUGH_NAMES[borough_code]},
                headers={"Ocp-Apim-Subscription-Key": settings.geoclient_app_key},
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.warning("geoclient transport %s attempt=%s", type(exc).__name__, attempt + 1)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if not resp.ok:
            return None
        addr = (resp.json() or {}).get("address") or {}
        return addr if addr.get("geosupportReturnCode") in ("00", "01") else None
    return None


def _split(address: str) -> tuple[str, str]:
    """The standard is "{HOUSE} {STREET}" and a house carries no space (ADR-582)."""
    house, _, street = address.partition(" ")
    return house, street


def stage_geoclient(db: Session, rate: float = 12.0, workers: int = 6,
                    limit: Optional[int] = None) -> dict:
    """Resumable: the queue is geo_enriched_at IS NULL, so a restart continues."""
    from app.services.place_geometry import (
        geometry_from_geoclient, pending_enrichment, span_from_geoclient,
        upsert_building_geometry)
    from app.services.segment_map import upsert_segments

    if not settings.geoclient_app_key:
        raise SystemExit("GEOCLIENT_APP_KEY is not set.")
    pace = _Pace(rate)
    counts = {"looked_up": 0, "matched": 0, "missed": 0}
    done = 0
    last_id = None
    while limit is None or done < limit:
        size = _BATCH if limit is None else min(_BATCH, limit - done)
        batch = pending_enrichment(db, size, after_id=last_id)
        if not batch:
            break
        last_id = batch[-1][0]

        def look(row):
            _id, address, _bk, borough = row
            pace.wait()
            house, street = _split(address)
            return row, geoclient_address(house, street, borough)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(look, batch))

        buildings, segments = [], []
        for (_id, address, block_key, borough), resp in results:
            counts["looked_up"] += 1
            # A miss is marked enriched too, so the queue drains; geo_grc stays NULL.
            geo = geometry_from_geoclient(resp) if resp else {}
            counts["matched" if resp else "missed"] += 1
            buildings.append({**geo, "normalised_address": address,
                              "block_key": block_key, "borough": borough})
            if resp:
                span = span_from_geoclient(resp)
                if span.get("segment_id"):
                    span.update({
                        "street_name": " ".join((resp.get("firstStreetNameNormalized") or "").split()) or None,
                        "borough": BOROUGH_NAMES[borough],
                        "block_key": block_key,
                        "lat": geo.get("lat"), "lng": geo.get("lng"),
                        "source": "city_seed",
                    })
                    segments.append(span)
        upsert_building_geometry(db, buildings, mark_enriched=True)
        if segments:
            upsert_segments(db, segments)
        db.commit()
        done += len(batch)
        logger.info("geoclient %s", counts)
    return counts


# ── stage: nodes ────────────────────────────────────────────────────────────

def stage_nodes(db: Session, limit: Optional[int] = None) -> dict:
    from app.services.segment_map import segments_without_nodes, walk_connectors

    rows = segments_without_nodes(db, limit)
    written = 0
    by_boro: dict[str, list] = {}
    for street, cross_one, cross_two, borough in rows:
        by_boro.setdefault(borough or "manhattan", []).append((street, cross_one, cross_two))
    for boro, triples in by_boro.items():
        for i in range(0, len(triples), _BATCH):
            written += walk_connectors(db, triples[i:i + _BATCH], borough=boro)
            db.commit()
            logger.info("nodes borough=%s written=%s of %s", boro, written, len(rows))
    # Measured on the local trial (2026-10-23): of 20 lookups, 16 filled the
    # segment asked about and 4 returned a NEIGHBOURING segment (stored as a
    # connector row). The 4 originals still lack nodes, so this stage is ONE
    # PASS, not a queue that drains: a re-run repeats its misses.
    left = len(segments_without_nodes(db))
    return {"segments_without_nodes": len(rows), "written": written,
            "filled": len(rows) - min(left, len(rows)) if limit is None else None,
            "still_without_nodes": left}


STAGES = {"schema": stage_schema, "addresspoint": stage_addresspoint,
          "geoclient": stage_geoclient, "nodes": stage_nodes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stages", nargs="+", choices=list(STAGES))
    ap.add_argument("--limit", type=int, default=None, help="geoclient/nodes: stop after N rows (a trial run)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    db = writer_session()
    try:
        for name in args.stages:
            fn = STAGES[name]
            kwargs = {"limit": args.limit} if name in ("geoclient", "nodes") else {}
            logger.info("stage %s: %s", name, fn(db, **kwargs))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
