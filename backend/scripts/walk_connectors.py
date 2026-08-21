"""Fetch + persist connector segments for a manifest, then report connectivity.

ADR-236 D2. The segment graph fragments because we only ever resolve segments for
PACKAGE addresses — the avenue stretches between clusters carry no packages, so
there is no node to path through. This walks each cross street between the
CONSECUTIVE streets that name it (via /blockface.json) and persists the result.

Bounds must be the same kind of street: "10 AVE between W 23 ST and W 24 ST" is a
real block-face; "10 AVE between W 23 ST and 9 AVE" is geometrically meaningless
and returns nothing.

Usage:
    docker compose exec -T backend python scripts/walk_connectors.py <manifest.csv>

Idempotent — re-running re-uses persisted segments and only fetches what is missing.
"""
import csv
import sys
import time
from collections import defaultdict, deque

sys.path.insert(0, "/app")

from app.database import SessionLocal              # noqa: E402
from app.models.street_segment import StreetSegment  # noqa: E402
from app.services.segment_map import (              # noqa: E402
    fetch_blockface, upsert_segments,
)
from app.tasks.enrich_manifest import _street_of, _street_sort_key  # noqa: E402

# GeoClient allows 5,000 req/min. This is a few hundred calls; a small delay keeps
# us far under the cap without meaningfully slowing the run.
_DELAY_S = 0.02


def connectivity(db) -> tuple[int, int, int]:
    """(segments, components, largest) over the persisted graph."""
    segs = db.query(StreetSegment).all()
    node = defaultdict(set)
    for s in segs:
        for n in (s.from_lion_node_id, s.to_lion_node_id):
            if n:
                node[n].add(s.segment_id)
    adj = defaultdict(set)
    for shared in node.values():
        for a in shared:
            adj[a] |= (shared - {a})

    ids = {s.segment_id for s in segs}
    seen, comps = set(), []
    for x in ids:
        if x in seen:
            continue
        q, comp = deque([x]), {x}
        seen.add(x)
        while q:
            y = q.popleft()
            for z in adj.get(y, ()):
                if z not in seen:
                    seen.add(z)
                    comp.add(z)
                    q.append(z)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return len(ids), len(comps), (len(comps[0]) if comps else 0)


def main(path: str) -> None:
    rows = [r for r in csv.DictReader(open(path)) if r.get("block_key")]

    # Which streets does each cross street bound? Walk it between consecutive ones.
    by_cross: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        street = _street_of(r.get("normalised_address"))
        if not street:
            continue
        for key in ("first_cross_street", "second_cross_street"):
            cross = (r.get(key) or "").strip()
            if cross and cross != street:
                by_cross[cross].add(street)

    pairs = set()
    for cross, streets in by_cross.items():
        ordered = sorted(streets, key=_street_sort_key)
        for a, b in zip(ordered, ordered[1:]):
            pairs.add((cross, a, b))
    pairs = sorted(pairs)

    db = SessionLocal()
    try:
        n0, c0, l0 = connectivity(db)
        print(f"BEFORE: {n0} segments | {c0} components | largest {l0} ({l0/max(n0,1):.0%})")
        print(f"connector lookups to make: {len(pairs)}\n")

        found, miss = [], 0
        t0 = time.perf_counter()
        for i, (on, a, b) in enumerate(pairs, 1):
            seg = fetch_blockface(on, a, b)
            if seg:
                found.append(seg)
            else:
                miss += 1
            if i % 50 == 0:
                print(f"  {i}/{len(pairs)}  found={len(found)} miss={miss}")
            time.sleep(_DELAY_S)
        elapsed = time.perf_counter() - t0

        stored = upsert_segments(db, found)
        db.commit()

        n1, c1, l1 = connectivity(db)
        print(f"\nfetched {len(found)} connectors ({miss} misses) in {elapsed:.1f}s; stored {stored}")
        print(f"AFTER:  {n1} segments | {c1} components | largest {l1} ({l1/max(n1,1):.0%})")
        print(f"\ncomponents {c0} -> {c1}   connectivity {l0/max(n0,1):.0%} -> {l1/max(n1,1):.0%}")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/manifest.csv")
