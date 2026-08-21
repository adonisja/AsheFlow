"""Compute and persist the sort-decision record (ADR-273).

WHAT THIS MEASURES
The three composition metrics ADR-272 is judged on, computed from the routes a
sort produced:

  blocks_split   a block LISTED on more than one route
  orphan_blocks  a block on a route with no adjacency to any sibling block there
  runt_routes    routes carrying <= 2 totes

TWO DEFINITIONS OF "SPLIT", AND WHY THIS ONE
The ADR-272 offline harness counted a split by TOTE DOMINANCE — a block whose
own totes landed on different routes. Measured on Morgan 2026-08-15 that gives
26. This module counts by BLOCK PRESENCE — a block appearing in more than one
route's block_keys — which gives 52 on the same sort.

Both are correct; they answer different questions. Presence is a strict superset
of dominance, because a route lists a block if it carries ANY package for it,
including a rider inside a tote that is dominant somewhere else. Post-sort, the
Route row records which blocks it carries, NOT which totes were dominant where —
that grouping exists only inside the sort. Recomputing dominance here would mean
re-reading the Redis manifest, which expires in 24h and is gone by the time the
nightly rollup runs.

Presence is also the better operational measure: it counts "how many walkers
will show up on this block today", which is the thing the owner objected to.
Just do not compare this number against the harness's and expect them to match.

plus the input shape (block group sizes) that explains them: a route holds 6
tote-slots, blocks arrive in groups of 3-4, and 6 rarely divides evenly by
3-or-4 without splitting something.

NEVER FAILS THE SORT
Telemetry is an optimisation, not a dependency — the same rule the
`segment_adjacency` load already follows in commit-sort. Every entry point here
is wrapped by the caller in try/except; a metric we could not compute must
never cost a truck its routes.

WHY THE ADJACENCY GRAPH IS REBUILT HERE
`orphan_blocks` needs to know which blocks border each other, and that graph
lives inside the proprietary sort. Rather than widen the sort's return type,
this recomputes it from the same `block_key` set. The cost is one pass over
blocks; the benefit is that this module stays public and independently testable.

Public module: aggregation and counting, no routing algorithm.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# A route carrying this many totes or fewer is a "runt" — too small to be a
# sensible trip, and the signature of a stranded block remainder (ADR-272).
RUNT_TOTE_THRESHOLD = 2


def _block_adjacency(block_keys: Iterable[str]) -> dict[str, set[str]]:
    """Structural adjacency over block_keys, mirroring _build_adjacency_graph.

    Reproduces the two COORDINATE-FREE edge types only:
      same street, adjacent hundred range   (W_32_St_300 <-> W_32_St_400)
      parallel street, same hundred range   (W_31_St_300 <-> W_32_St_300)

    Cross-street (cost-1) edges are deliberately NOT reproduced: they need
    per-package cross-street strings that are not on the Route row. Omitting
    them makes this measure CONSERVATIVE — it can over-report an orphan whose
    only link was a cross-street edge, never under-report one. A metric that
    errs toward flagging is the right bias for a regression alarm.
    """
    parsed: dict[str, tuple] = {}
    for bk in block_keys:
        parts = (bk or "").split("_")
        # Named forms (Broadway_700) and sentinels (__unknown_*) have no
        # direction/type triple and simply get no structural edges.
        if len(parts) != 4:
            continue
        direction, street, stype, hundred = parts
        try:
            parsed[bk] = (direction, int(street), stype, int(hundred))
        except ValueError:
            continue

    adj: dict[str, set[str]] = defaultdict(set)
    keys = list(parsed)
    for i, a in enumerate(keys):
        da, sa, ta, ha = parsed[a]
        for b in keys[i + 1:]:
            dbk, sb, tb, hb = parsed[b]
            same_street = (da, sa, ta) == (dbk, sb, tb)
            if same_street and abs(ha - hb) == 100:
                adj[a].add(b)
                adj[b].add(a)
            elif da == dbk and ta == tb and abs(sa - sb) == 1 and ha == hb:
                adj[a].add(b)
                adj[b].add(a)
    return adj


def compute_sort_metrics(routes: list) -> dict:
    """Composition metrics for a set of persisted Route rows.

    `routes` are ORM Route objects (or any object exposing block_keys,
    tote_ids, slot_cost, capacity_limit, closed_reason). Returns the dict of
    columns RouteSortRun stores.
    """
    if not routes:
        return {
            "routes_out": 0, "blocks_split": 0, "orphan_blocks": 0,
            "runt_routes": 0, "capacity_util_pct": None,
            "blocks_per_route_hist": {}, "closed_reason_hist": {},
            "blocks_in": 0, "totes_in": 0, "packages_in": 0,
            "block_group_sizes": {},
        }

    # Which routes touch each block.
    where: dict[str, set[int]] = defaultdict(set)
    for i, r in enumerate(routes):
        for bk in (r.block_keys or []):
            where[bk].add(i)

    blocks_split = sum(1 for rs in where.values() if len(rs) > 1)

    all_blocks = set(where)
    adj = _block_adjacency(all_blocks)
    orphan_blocks = 0
    for r in routes:
        bs = set(r.block_keys or [])
        if len(bs) < 2:
            continue  # a single-block route cannot have an orphan
        for bk in bs:
            if not (adj.get(bk, set()) & (bs - {bk})):
                orphan_blocks += 1

    tote_counts = [len(r.tote_ids or []) for r in routes]
    runt_routes = sum(1 for n in tote_counts if n <= RUNT_TOTE_THRESHOLD)

    # Utilisation against each route's OWN lock — capacity varies per route
    # (heavy blocks lower it, paired routes raise it), so a single divisor
    # would misreport. Routes with no lock recorded are skipped.
    caps = [(r.slot_cost or 0, r.capacity_limit or 0) for r in routes]
    usable = [(c, k) for c, k in caps if k > 0]
    capacity_util_pct = (
        round(100.0 * sum(c for c, _ in usable) / sum(k for _, k in usable), 2)
        if usable else None
    )

    bpr = Counter(len(set(r.block_keys or [])) for r in routes)
    closed = Counter(
        (getattr(r, "closed_reason", None) or "unrecorded") for r in routes
    )

    return {
        "routes_out": len(routes),
        "blocks_split": blocks_split,
        "orphan_blocks": orphan_blocks,
        "runt_routes": runt_routes,
        "capacity_util_pct": capacity_util_pct,
        "blocks_per_route_hist": {str(k): v for k, v in sorted(bpr.items())},
        "closed_reason_hist": dict(closed),
        "blocks_in": len(all_blocks),
        "totes_in": sum(tote_counts),
        "packages_in": sum((r.package_count or 0) for r in routes),
        "block_group_sizes": {},   # filled by the caller, which sees the pre-sort grouping
    }


def record_sort_run(
    db: Session,
    *,
    company_id: UUID,
    truck_assignment_id: UUID,
    route_date,
    routes: list,
    tuning,
    crew_size: Optional[int],
    paired_route_count: int,
    t_factor: float,
    p_factor: float,
    urgency_blocks: int,
    workload_blocks: int,
    boundary_present: bool,
    block_group_sizes: Optional[dict] = None,
):
    """Append one RouteSortRun. Returns the row (not committed).

    run_seq is derived per (company, assignment, date) so a re-sort appends
    rather than replaces — the whole point of the table. The caller owns the
    commit, so this participates in the existing flush/audit/commit sequence.
    """
    from app.models.route_sort_run import RouteSortRun

    metrics = compute_sort_metrics(routes)
    if block_group_sizes is not None:
        metrics["block_group_sizes"] = block_group_sizes

    # Next sequence for this truck-day. Scoped by company_id (Dimension 1) even
    # though truck_assignment_id is already unique — a cross-tenant read here
    # would leak the shape of another company's operation.
    prev = (
        db.query(func.max(RouteSortRun.run_seq))
        .filter(
            RouteSortRun.company_id == company_id,
            RouteSortRun.truck_assignment_id == truck_assignment_id,
            RouteSortRun.route_date == route_date,
        )
        .scalar()
    )

    row = RouteSortRun(
        company_id=company_id,
        truck_assignment_id=truck_assignment_id,
        route_date=route_date,
        run_seq=(prev or 0) + 1,
        algorithm_version=tuning.algorithm_version,
        crew_size=crew_size,
        paired_route_count=paired_route_count,
        t_factor=t_factor,
        p_factor=p_factor,
        urgency_blocks=urgency_blocks,
        workload_blocks=workload_blocks,
        boundary_present=boundary_present,
        **tuning.as_telemetry(),
        **metrics,
    )
    db.add(row)
    db.flush()
    return row
