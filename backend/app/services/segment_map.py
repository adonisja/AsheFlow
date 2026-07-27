"""Persistent LION segment map — write-through cache + connector walk (ADR-236).

Route adjacency is "two segments share a LION node" (ADR-196). We only ever
resolved segments for PACKAGE addresses, so the connecting streets were absent and
the graph shattered: measured **47 disconnected components, largest holding 6%** of
segments on a real 10k-package manifest.

Two mechanisms fix that, both here:

1. ``upsert_segments`` — persist what enrichment already resolved, instead of
   discarding it with the manifest's 24h Redis TTL. Self-seeding: the map densifies
   from work already happening, so the first sort in a territory pays full GeoClient
   cost and later sorts hit the table.

2. ``walk_connectors`` — fetch the segments *between* cross streets via GeoClient
   ``/blockface.json``, which returns ``segmentIdentifier`` + ``fromNode``/``toNode``.
   Verified on real data: walking 9 AVENUE across consecutive cross streets yields
   segments that chain by shared node (0033838 → 0033840 → 0033842 → 0033846), i.e.
   a genuine path along the avenue.

Deliberately global (no company_id) — see the StreetSegment model docstring.

Everything here is best-effort: GeoClient being down must degrade routing to
block_key adjacency, never fail a sort.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import requests
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.street_segment import StreetSegment

logger = logging.getLogger(__name__)

_GEOCLIENT_BASE = "https://api.nyc.gov/geoclient/v2"
_TIMEOUT = 8

# A blockface lookup that returns HTTP 200 but no segmentIdentifier is a normal
# miss (observed on 9 Ave, W 40->W 41), not an error: the graph keeps that gap and
# block_key adjacency covers it.
SOURCE_PACKAGE = "package_address"
SOURCE_CONNECTOR = "connector_walk"


def upsert_segments(db: Session, segments: Iterable[dict]) -> int:
    """Idempotently persist segments. Returns the number submitted.

    `segments` are dicts with at least `segment_id`; other keys are optional.
    Concurrent sorts from different companies will upsert the same public segment,
    so this uses ON CONFLICT DO UPDATE keyed on segment_id — a race cannot raise
    and cannot duplicate. `last_seen_at` is refreshed so staleness has a real
    signal (every sort re-touches its segments).
    """
    rows = [s for s in segments if s.get("segment_id")]
    if not rows:
        return 0

    # Deduplicate within the batch: ON CONFLICT cannot fire twice for the same key
    # in a single statement ("cannot affect row a second time").
    by_id: dict[str, dict] = {}
    for s in rows:
        by_id[str(s["segment_id"])] = s

    payload = []
    for sid, s in by_id.items():
        payload.append({
            "segment_id":        sid,
            "from_lion_node_id": s.get("from_lion_node_id"),
            "to_lion_node_id":   s.get("to_lion_node_id"),
            "street_name":       s.get("street_name"),
            "borough":           s.get("borough"),
            "block_key":         s.get("block_key"),
            "lat":               s.get("lat"),
            "lng":               s.get("lng"),
            "source":            s.get("source") or SOURCE_PACKAGE,
        })

    stmt = pg_insert(StreetSegment).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[StreetSegment.segment_id],
        set_={
            # Refresh topology only when the new row actually has it — a later
            # partial lookup must not blank out good data.
            "from_lion_node_id": stmt.excluded.from_lion_node_id,
            "to_lion_node_id":   stmt.excluded.to_lion_node_id,
            "last_seen_at":      func.now(),
        },
    )
    db.execute(stmt)
    return len(payload)


def known_segment_ids(db: Session, segment_ids: Iterable[str]) -> set[str]:
    """Which of these segments are already mapped (so we can skip re-fetching)."""
    ids = [str(s) for s in segment_ids if s]
    if not ids:
        return set()
    rows = db.execute(
        select(StreetSegment.segment_id).where(StreetSegment.segment_id.in_(ids))
    ).scalars().all()
    return set(rows)


def fetch_blockface(
    on_street: str,
    cross_one: str,
    cross_two: str,
    borough: str = "manhattan",
) -> Optional[dict]:
    """One connector segment between two cross streets, or None.

    GeoClient ``/blockface.json`` is the only endpoint that returns segment
    topology for a stretch of street (``/intersection`` returns coordinates and
    census/political fields but NO segment ids; ``/segment.json`` and
    ``/street.json`` do not exist — all verified by probe).
    """
    if not settings.geoclient_app_key:
        return None
    try:
        resp = requests.get(
            f"{_GEOCLIENT_BASE}/blockface.json",
            params={
                "onStreet": on_street,
                "crossStreetOne": cross_one,
                "crossStreetTwo": cross_two,
                "borough": borough,
            },
            headers={"Ocp-Apim-Subscription-Key": settings.geoclient_app_key},
            timeout=_TIMEOUT,
        )
        if not resp.ok:
            logger.debug(
                "blockface HTTP %s for %s between %s and %s",
                resp.status_code, on_street, cross_one, cross_two,
            )
            return None
        bf = (resp.json() or {}).get("blockface") or {}
        sid = bf.get("segmentIdentifier")
        if not sid:
            # 200 with no segment — a real, expected miss. Not an error.
            return None
        return {
            "segment_id":        str(sid),
            "from_lion_node_id": bf.get("fromNode"),
            "to_lion_node_id":   bf.get("toNode"),
            "street_name":       on_street,
            "borough":           borough,
            "source":            SOURCE_CONNECTOR,
        }
    except Exception as exc:  # noqa: BLE001 — best effort; never fail a sort
        logger.warning(
            "blockface lookup failed for %s (%s): %s",
            on_street, cross_one, type(exc).__name__,
        )
        return None


def walk_connectors(
    db: Session,
    cross_street_pairs: Iterable[tuple[str, str, str]],
    borough: str = "manhattan",
) -> int:
    """Resolve + persist connector segments. Returns how many were stored.

    `cross_street_pairs` is (on_street, cross_one, cross_two) — the stretch of
    `on_street` between two cross streets. Bounded by the manifest's distinct cross
    streets (39 on the measured manifest, i.e. ~80 lookups against 10,363 address
    lookups — under 1% additional work) so this cannot run away.
    """
    found: list[dict] = []
    for on_street, c1, c2 in cross_street_pairs:
        seg = fetch_blockface(on_street, c1, c2, borough)
        if seg:
            found.append(seg)
    if not found:
        return 0
    return upsert_segments(db, found)


def load_node_adjacency(db: Session, segment_ids: Iterable[str]) -> dict[str, set[str]]:
    """LION NODE adjacency for misroute detection (ADR-238 D4b).

    Returns {node_id: {adjacent node_ids}} — two nodes are adjacent iff a segment
    connects them. This mirrors `route_sort._build_node_adjacency`, but sourced
    from the PERSISTED map rather than only the segments this sort happens to
    carry, so it includes the connector segments that bridge clusters (99%
    connected vs a 47-component per-sort reconstruction).

    Scoped to the neighbourhood of `segment_ids`: we take those segments' nodes,
    then every segment touching them (one hop out), so connectors are included
    without loading all of NYC. Empty input or empty map → {} (caller degrades to
    its own topology).
    """
    ids = {str(s) for s in segment_ids if s}
    if not ids:
        return {}

    seeds = db.execute(
        select(StreetSegment).where(StreetSegment.segment_id.in_(ids))
    ).scalars().all()
    nodes = {n for s in seeds for n in (s.from_lion_node_id, s.to_lion_node_id) if n}
    if not nodes:
        return {}

    # One hop out: segments touching those nodes — this is what pulls in the
    # connectors, which carry no packages and so are never in `segment_ids`.
    nearby = db.execute(
        select(StreetSegment).where(
            (StreetSegment.from_lion_node_id.in_(nodes))
            | (StreetSegment.to_lion_node_id.in_(nodes))
        )
    ).scalars().all()

    adj: dict[str, set[str]] = {}
    for s in nearby:
        a, b = s.from_lion_node_id, s.to_lion_node_id
        if a and b and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    return adj


def load_adjacency(db: Session, segment_ids: Iterable[str]) -> dict[str, set[str]]:
    """Segment adjacency from the map: two segments are adjacent iff they share a
    LION node (ADR-196).

    Expands one hop beyond the requested set so connector segments (which carry no
    packages, and so are never in `segment_ids`) can still bridge two clusters —
    that is the entire point of persisting them.
    """
    ids = {str(s) for s in segment_ids if s}
    if not ids:
        return {}

    seeds = db.execute(
        select(StreetSegment).where(StreetSegment.segment_id.in_(ids))
    ).scalars().all()
    nodes = {n for s in seeds for n in (s.from_lion_node_id, s.to_lion_node_id) if n}
    if not nodes:
        return {}

    # Every segment touching those nodes, including connectors we hold no packages for.
    neighbours = db.execute(
        select(StreetSegment).where(
            (StreetSegment.from_lion_node_id.in_(nodes))
            | (StreetSegment.to_lion_node_id.in_(nodes))
        )
    ).scalars().all()

    node_segs: dict[str, set[str]] = {}
    for s in neighbours:
        for n in (s.from_lion_node_id, s.to_lion_node_id):
            if n:
                node_segs.setdefault(n, set()).add(s.segment_id)

    adj: dict[str, set[str]] = {}
    for shared in node_segs.values():
        for a in shared:
            adj.setdefault(a, set()).update(shared - {a})
    return adj
