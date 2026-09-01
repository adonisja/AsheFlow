"""Unregistered package intake (ADR-246).

A walker finds a package in their tote that was never registered — not on any
manifest, not on any route. This decides what happens to it.

Ownership is decided BEFORE routing:

    1. in the company zone?   no  -> not ours, becomes a PackageRemoval
    2. best-fit route?
    3. adder on that route?   no  -> warn, or absorb if the best fit has departed

Public module by design: it holds no proprietary routing algorithm. Best-fit is
a straightforward block/stop proximity match, not the clustering that lives in
the gitignored sort services.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import CompanyZone

logger = logging.getLogger(__name__)
from app.models.delivery_stop import DeliveryStop
from app.models.employee import Employee
from app.models.walker_route import Route


# A route that has departed cannot take on a package: its walker may already be
# past the stop, or heading somewhere the package is not (ADR-246).
#
# The model documents the lifecycle as unassigned|assigned|in_progress|completed
# (walker_route.py:63). "locked" also appears in walker_routes.py — a route
# finalised but not yet started — so it is included as still-accepting. The set
# is expressed as what CAN accept rather than what cannot, so an unrecognised
# status fails closed: a route in an unknown state is not handed a package.
_ACCEPTING_STATUSES = {"unassigned", "assigned", "locked"}


@dataclass
class ZoneVerdict:
    """Whether the package is the company's to deliver."""
    in_zone: bool
    decidable: bool                  # False when we lack coords or a boundary
    reason: Optional[str] = None     # no_coords | no_boundary | outside


@dataclass
class RouteCandidate:
    route_id: UUID
    route_number: Optional[int]
    walker_id: Optional[UUID]
    walker_name: Optional[str]
    status: Optional[str]
    can_accept: bool
    match: str                       # address | block_key | near_segment | near_block
    # How far away, in the unit of the tier that matched: graph hops for
    # near_segment, hundred-blocks for near_block. None on an exact match.
    # Kept distinct from `match` so the UI can say "2 blocks away" rather than
    # implying a precision the tier does not have (ADR-260).
    distance: Optional[float] = None
    is_adders_route: bool = False


@dataclass
class IntakeAssessment:
    """The decision, before anything is written."""
    zone: ZoneVerdict
    best_fit: Optional[RouteCandidate] = None
    adders_route: Optional[RouteCandidate] = None
    candidates: list[RouteCandidate] = field(default_factory=list)
    # Whether ANY route exists for the date, regardless of match (ADR-260).
    #
    # Not a branch — a found package is found by a walker already deployed, so
    # routes always exist by then. It is reported so the UI can tell a
    # dispatcher "the day is not sorted yet" instead of "no route is near",
    # which would send them looking for a routing problem that is really a
    # not-yet-run sort.
    routes_exist: bool = False
    # Set when the best fit cannot take it and something else absorbed it.
    absorbed_reason: Optional[str] = None


def load_company_boundary(db: Session, company_id: UUID) -> list[dict]:
    """The active top-level company zone as [{lat, lng}], or [].

    Mirrors run_sort._get_company_boundary. Duplicated rather than imported
    because run_sort pulls in the whole sort pipeline, and intake needs only
    this one lookup.
    """
    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .order_by(CompanyZone.created_at.desc())
        .first()
    )
    if zone is None or not zone.bounds:
        return []
    coords = zone.bounds.get("coordinates", [[]])[0]
    return [{"lat": c[1], "lng": c[0]} for c in coords]


def check_zone(
    db: Session,
    company_id: UUID,
    lat: Optional[float],
    lng: Optional[float],
) -> ZoneVerdict:
    """Is this package inside the company's authorised area?

    Reuses membership_boundary (ADR-214), which edge-buffers the polygon — a
    package on the boundary line belongs to us, and a raw polygon would reject
    it on a rounding error.

    `decidable=False` is a distinct answer from `in_zone=False`: without coords
    or a boundary we cannot prove the package is foreign, and declaring it so
    would strand a deliverable package. ADR-246 sends those to dispatch instead.
    """
    if lat is None or lng is None:
        return ZoneVerdict(in_zone=False, decidable=False, reason="no_coords")

    boundary = load_company_boundary(db, company_id)
    if not boundary:
        return ZoneVerdict(in_zone=False, decidable=False, reason="no_boundary")

    from shapely.geometry import Point
    from app.services.cluster_packages import membership_boundary

    poly = membership_boundary(boundary)
    inside = poly.covers(Point(lng, lat))
    return ZoneVerdict(
        in_zone=bool(inside),
        decidable=True,
        reason=None if inside else "outside",
    )


@dataclass
class ResolvedAddress:
    """What the server worked out from the label text (ADR-259).

    `geocoded` records whether GeoClient answered, which is what separates
    "outside the zone" from "ownership unconfirmed" downstream. The block key is
    derived offline, so it survives a GeoClient outage and the block-match tier
    keeps working when the zone check cannot.
    """
    lat: Optional[float] = None
    lng: Optional[float] = None
    normalised_address: Optional[str] = None
    block_key: Optional[str] = None
    # LION segment the address sits on — the package-side anchor for proximity
    # ranking against Route.segment_ids (ADR-260). Only GeoClient supplies it.
    segment_id: Optional[str] = None
    geocoded: bool = False


def resolve_address(
    db: Session,
    company_id: UUID,
    raw_address: Optional[str],
    tba: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    block_key: Optional[str] = None,
    normalised_address: Optional[str] = None,
) -> ResolvedAddress:
    """Derive coords, a normalised address and a block key from label text.

    Clients send what they read off the label; nothing operational depends on
    them supplying coordinates. Anything the caller DID pass wins — mobile may
    one day send a device fix, and a dispatcher may correct a bad parse by hand.

    Two derivations, deliberately independent (ADR-259):

      * `derive_block_key` is pure string work, so a GeoClient outage still
        leaves routes rankable by block.
      * `_geoclient_normalise` answers ownership AND supplies the normalised
        address for the exact-building match tier, in one call.

    Never raises: intake must reach dispatch even when geocoding fails, so a
    GeoClient error degrades to `geocoded=False` and the caller escalates
    (ADR-246).
    """
    out = ResolvedAddress(
        lat=lat, lng=lng,
        normalised_address=normalised_address,
        block_key=block_key,
        geocoded=lat is not None and lng is not None,
    )

    if not raw_address:
        return out

    if out.block_key is None:
        from app.services.derive_block_key import derive_block_key
        parsed = derive_block_key(raw_address, tba)
        # UnparseableAddress is a normal outcome for a label the OCR mangled;
        # it carries a reason, not a block key, and leaves the tier unmatched.
        out.block_key = getattr(parsed, "block_key", None)

    if out.lat is not None and out.lng is not None:
        return out

    borough = _company_borough(db, company_id)
    try:
        # ADR-316 — PlaceType first, GeoClient on a miss. Aliased because this
        # module already has a `resolve_address` of its own (a different job:
        # this one answers ownership, that one answers geometry).
        from app.services.address_resolver import resolve_address as _resolve_geo
        geo = _resolve_geo(db, raw_address, borough=borough)
    except Exception as exc:
        # Network, timeout, malformed upstream payload. Ownership stays
        # undecidable and the package escalates — never a 500 at the edge.
        #
        # Deliberately NOT exc_info=True: the traceback frames carry
        # `raw_address`, a customer delivery address, straight into the logs
        # (Dimension 7). The exception type is what identifies an outage; the
        # address adds nothing an operator can act on.
        logger.warning("intake geocode failed: %s", type(exc).__name__)
        return out

    if geo is None or geo.lat is None or geo.lng is None:
        return out

    out.lat, out.lng = geo.lat, geo.lng
    out.segment_id = geo.segment_id
    out.geocoded = True
    # GeoClient's canonical form is what Route.normalised_addresses holds, so
    # preferring it is what makes the exact-address tier able to match at all.
    if geo.normalised_address:
        out.normalised_address = geo.normalised_address
    return out


def _company_borough(db: Session, company_id: UUID) -> str:
    """Borough for GeoClient lookups: company config, else Manhattan.

    Same resolution order as sort.py:774 — an operator outside Manhattan sets
    it on CompanyConfig, and the default is only a default.
    """
    from app.models.company import CompanyConfig
    cfg = (
        db.query(CompanyConfig)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    return (cfg.geoclient_borough if cfg and cfg.geoclient_borough else None) or "manhattan"


_MAX_SEGMENT_HOPS = 3
"""How far to walk the segment graph looking for a route.

Three hops is roughly a couple of blocks on the LION grid. Beyond that
"proximity" stops meaning anything operational — a walker is not detouring six
segments for one found package, and an unbounded BFS on a dense graph would
rank every route in midtown as a candidate.
"""

_MAX_BLOCK_RADIUS = 2
"""How many blocks away still counts as "near", in blocks (ADR-260).

Two, because the operator runs many walkers in a dense area: within two blocks
at least one route will almost always match, and it is a short enough detour
that handing the package over is not an imposition on the walker.

Note this is in BLOCKS, not hundred-block units. `W_37_St_500` reaches
`W_37_St_300` on the same street, and `W_35_St`/`W_39_St` across streets.
"""


@dataclass(frozen=True)
class _Block:
    """A block key decomposed into its grid coordinates.

    `W_37_St_500` -> direction "W", street 37, type "St", hundred 500.

    The whole point is that a block key is not an opaque string: it carries a
    position on the street grid, and "one block away" moves along EITHER axis.
    From W 37th St & the 500 block, all of these are one block away:

        W_37_St_400   along the street (down one hundred-block)
        W_36_St_500   one street over
        W_38_St_500   one street the other way

    Ranking only the hundred-block, as the first cut did, misses two thirds of
    a package's actual neighbours.
    """
    direction: str      # N/S/E/W, or "" for an avenue with no direction
    street: int         # 37 in W_37_St, 10 in 10_Ave
    kind: str           # St | Ave | Pl | Blvd ... — normalised lowercase
    hundred: int        # the trailing hundred-block


# W_37_St_500 / E_9_St_100 — a directional cross street.
_NUMBERED_DIR = re.compile(r"^([NSEW])_(\d+)_([A-Za-z]+)_(\d+)$", re.I)
# 10_Ave_500 — a numbered avenue, no direction.
_NUMBERED_PLAIN = re.compile(r"^(\d+)_([A-Za-z]+)_(\d+)$", re.I)


def _parse_block_key(key: str) -> Optional[_Block]:
    """Decompose a block key into grid coordinates, or None if it is not on a grid.

    Named streets (`Jackson_Ave_21`, `Metropolitan_Ave_200`, `Steinway_St_31` —
    3 of 256 distinct keys on staging) deliberately return None. They have no
    numeric axis, so "one street over from Jackson Ave" is not computable from
    the key alone; those fall to the segment graph, which does know what
    connects. Guessing a neighbour for them would be worse than admitting we
    cannot tell.

    DUPLICATES `route_sort._parse_block_key`, which splits the same four
    components, and the duplication is forced: route_sort is proprietary and
    gitignored, this module is deliberately public (it holds no routing
    algorithm), so importing across that line would drag a private module into
    a public one. Same reason load_company_boundary duplicates
    run_sort._get_company_boundary.

    The two are NOT interchangeable, and a caller must not assume they are:
      * no direction -> "" here, None there
      * `kind` is lowercased here, case-preserved there
    Both are internal to their own module. If block-key parsing ever has to be
    shared for real, it belongs in a third public module that both import —
    not in one calling the other.
    """
    m = _NUMBERED_DIR.match(key)
    if m:
        return _Block(m.group(1).upper(), int(m.group(2)),
                      m.group(3).lower(), int(m.group(4)))
    m = _NUMBERED_PLAIN.match(key)
    if m:
        return _Block("", int(m.group(1)), m.group(2).lower(), int(m.group(3)))
    return None


def _block_distance(a: _Block, b: _Block) -> Optional[int]:
    """Distance in blocks between two grid positions, or None if incomparable.

    Two ways to be near, and they are not additive — a package is either along
    the same street or on a nearby parallel one:

      same street (`W_37_St`)   -> hundred-blocks apart / 100
      same hundred (`_500`)     -> streets apart

    Cross-axis pairs (`W_37_St_500` vs `W_36_St_300`) return None rather than a
    diagonal: that is two blocks over AND two along, which is not what an
    operator means by "one block away", and the segment graph handles genuine
    corner cases better than arithmetic on a key.

    Different direction (`W` vs `E`) or type (`St` vs `Ave`) is never near:
    W 37th and E 37th are opposite sides of Fifth Avenue, and 37th St has no
    relation to 37th Ave.
    """
    if a.direction != b.direction or a.kind != b.kind:
        return None
    if a.street == b.street:
        return abs(a.hundred - b.hundred) // 100
    if a.hundred == b.hundred:
        return abs(a.street - b.street)
    return None


def _proximity_ranks(
    db: Session,
    routes: list,
    *,
    block_key: Optional[str],
    segment_id: Optional[str],
) -> dict:
    """{route_id: (tier, distance)} for routes that do NOT cover the block.

    Two tiers, tried in order (ADR-260):

      "segment"  LION adjacency — hops through the persisted graph (ADR-236/238).
                 Correct across streets, because it follows what connects.
      "block"    same street, hundred-block distance. Pure string work, so it
                 survives a geocode failure and works on routes built before
                 `segment_ids` existed.

    The fallback is not a placeholder: a route persisted before the ADR-260
    migration has `segment_ids == []`, and ranking it as "no match" would hide
    every route created today behind an empty picker.
    """
    out: dict = {}

    # ── tier 1: segment adjacency ────────────────────────────────────────────
    if segment_id:
        with_segments = [r for r in routes if r.segment_ids]
        if with_segments:
            from app.services.segment_map import load_adjacency

            known = {s for r in with_segments for s in r.segment_ids}
            # Seed the walk with the package's segment AND the routes' segments
            # so the query returns the connectors that bridge them — a graph
            # loaded from the package alone would stop at its own neighbours.
            adj = load_adjacency(db, known | {segment_id})

            # BFS from the package outward; the first time a route's segment is
            # reached, that hop count is its distance.
            frontier = {segment_id}
            seen = {segment_id}
            for hop in range(1, _MAX_SEGMENT_HOPS + 1):
                frontier = {n for s in frontier for n in adj.get(s, set())} - seen
                if not frontier:
                    break
                seen |= frontier
                for r in with_segments:
                    if r.id not in out and frontier & set(r.segment_ids):
                        out[r.id] = ("segment", float(hop))

    # ── tier 2: grid distance, along the street OR across it ─────────────────
    here = _parse_block_key(block_key) if block_key else None
    if here:
        for r in routes:
            if r.id in out:
                continue          # already ranked by the better tier
            best: Optional[int] = None
            for k in (r.block_keys or []):
                other = _parse_block_key(k)
                if other is None:
                    continue
                d = _block_distance(here, other)
                if d and (best is None or d < best):
                    best = d
            if best is not None and best <= _MAX_BLOCK_RADIUS:
                out[r.id] = ("block", float(best))

    return out


def find_best_fit(
    db: Session,
    company_id: UUID,
    route_date: date,
    block_key: Optional[str],
    normalised_address: Optional[str],
    adder_employee_id: Optional[UUID] = None,
    segment_id: Optional[str] = None,
) -> IntakeAssessment:
    """Rank today's routes for this package.

    Match strength, best first:
      1. the address is already a stop on that route  (exact — same building)
      2. the route covers that block_key              (same block)
      3. near by LION segment adjacency               (hops, ADR-260)
      4. near by same-street hundred-blocks           (fallback, ADR-260)

    Tiers 3 and 4 exist because "no route covers this block" is not the same
    answer as "no route can take this package". A route on the adjacent block
    is a real option, and dropping it produced a dead end for the dispatcher.

    Deliberately NOT the truck layer's centroid haversine (ADR-184): routes are
    block-based, and a centroid says nothing about whether a walker actually
    passes the address. Segment adjacency follows what actually connects.

    An empty result here is meaningful: with routes present it means nothing is
    near enough; with NO routes for the date it means the day has not been
    sorted yet, and the caller sends the package to the routing pool instead.
    """
    routes = (
        db.query(Route)
        .filter(Route.company_id == company_id, Route.route_date == route_date)
        .all()
    )

    exec_ids = {r.executor_id for r in routes if r.executor_id}
    names: dict = {}
    if exec_ids:
        from app.models.employee import Employee
        names = {
            e.id: e.name for e in
            db.query(Employee)
            .filter(Employee.id.in_(exec_ids), Employee.company_id == company_id)
            .all()
        }

    # Proximity for the routes that do NOT cover the block. Computed once for
    # the whole set rather than per route (ADR-260) — the segment tier needs a
    # single adjacency query, and doing it inside the loop would issue one per
    # candidate.
    prox = _proximity_ranks(db, routes, block_key=block_key, segment_id=segment_id)

    ranked: list[tuple[tuple[int, float], RouteCandidate]] = []
    for r in routes:
        if normalised_address and normalised_address in (r.normalised_addresses or []):
            strength, match, distance = (0, 0.0), "address", None
        elif block_key and block_key in (r.block_keys or []):
            strength, match, distance = (1, 0.0), "block_key", None
        else:
            # "No route covers this block" is not the same as "no route can
            # take it" (ADR-260). A route on the adjacent block is a real
            # option, and dropping it here is what produced a dead end.
            near = prox.get(r.id)
            if near is None:
                continue
            tier, distance = near
            # Tier 2 = segment adjacency (hops), 3 = same-street blocks. Both
            # sort after an exact match and before nothing.
            strength, match = (2 if tier == "segment" else 3, distance), f"near_{tier}"

        cand = RouteCandidate(
            route_id=r.id,
            route_number=r.route_number,
            walker_id=r.executor_id,
            walker_name=names.get(r.executor_id),
            status=r.status,
            can_accept=(r.status or "") in _ACCEPTING_STATUSES,
            match=match,
            distance=distance,
            is_adders_route=bool(adder_employee_id and r.executor_id == adder_employee_id),
        )
        ranked.append((strength, cand))

    # (tier, distance) — exact matches first, then nearest within each tier.
    ranked.sort(key=lambda t: t[0])
    candidates = [c for _, c in ranked]

    assessment = IntakeAssessment(
        zone=ZoneVerdict(in_zone=True, decidable=True),
        candidates=candidates,
        adders_route=next((c for c in candidates if c.is_adders_route), None),
        routes_exist=bool(routes),
    )

    if not candidates:
        return assessment

    top = candidates[0]
    if top.can_accept:
        assessment.best_fit = top
        return assessment

    # Best fit has departed. Absorb into the closest route that can still take
    # it — which may well be the adder's own, since they are holding it.
    fallback = next((c for c in candidates if c.can_accept), None)
    if fallback is not None:
        assessment.best_fit = fallback
        assessment.absorbed_reason = f"best_fit_in_progress:{top.route_number}"
        return assessment

    # EVERY nearby route has departed. The package still has to go out today —
    # refusing to place it means it sits at the station and misses its delivery
    # date, which is the outcome the whole intake path exists to prevent.
    #
    # So the departed rule is a PREFERENCE, not a gate: fall back to the best
    # match and ignore the in-progress status. The walker on that route is the
    # closest person to the address, and dispatch radios them. `absorbed_reason`
    # says this happened so the UI can tell the dispatcher they are assigning
    # onto a route already in the field (ADR-260).
    assessment.best_fit = top
    assessment.absorbed_reason = f"all_departed:{top.route_number}"
    return assessment


# ── duplicate guard ───────────────────────────────────────────────────────────

@dataclass
class DuplicateVerdict:
    """Whether this TBA is already known, and to whom."""
    is_duplicate: bool
    holder_name: Optional[str] = None
    route_number: Optional[int] = None
    route_id: Optional[UUID] = None
    basis: Optional[str] = None       # route_manifest | delivery_stop


def check_duplicate(
    db: Session,
    company_id: UUID,
    tba: str,
    route_date: date,
) -> DuplicateVerdict:
    """Is this package already registered? If so, who has it?

    **Never create a second delivery record for one TBA** (ADR-246). Two records
    for one physical package corrupt both the walker's metrics and the Amazon
    reconciliation, and the check is cheap and easy to omit.

    Returning the holder is the point, not a bonus. A bare refusal sends the
    walker off to discover who has it; naming them lets the field resolve it
    directly — and two people holding the same TBA is itself a real signal (a
    mislabelled package, or one already delivered).

    Scoped to `route_date`, not all time: the same TBA legitimately recurs
    across days (Amazon reuses them, and a redelivery is a new package-day).
    A global check would refuse today's package because it was delivered a
    fortnight ago.

    ### Why this is not `/packages/lookup` (ADR-245)

    That endpoint answers a different question — the *full timeline* across five
    sources, with suffix matching and ambiguity handling, for a dispatcher on a
    phone call. This needs one exact-match yes/no plus a name, on one date, as a
    precondition inside a write path. Reusing it would mean either an internal
    HTTP call or extracting a 150-line handler mid-flight; a scoped query is
    honest about needing less. The response shapes are deliberately unrelated.
    """
    needle = tba.strip().upper()
    if not needle:
        return DuplicateVerdict(is_duplicate=False)

    # Route manifest — the package is assigned but not yet delivered.
    route = (
        db.query(Route)
        .filter(
            Route.company_id == company_id,
            Route.route_date == route_date,
            Route.tba_numbers.any(needle),
        )
        .first()
    )
    if route is not None:
        holder = None
        if route.executor_id:
            emp = (
                db.query(Employee)
                .filter(Employee.id == route.executor_id,
                        Employee.company_id == company_id)
                .first()
            )
            holder = emp.name if emp else None
        return DuplicateVerdict(
            is_duplicate=True,
            holder_name=holder,
            route_number=route.route_number,
            route_id=route.id,
            basis="route_manifest",
        )

    # Delivery stop — a stop already covers it, possibly already delivered.
    #
    # DeliveryStop carries no date of its own (verified against the model), so
    # the day comes from its Route via the join. An unrouted stop cannot be
    # date-scoped and is therefore not considered here; the route-manifest check
    # above is the one that matters for a same-day duplicate.
    row = (
        db.query(DeliveryStop, Route.route_number)
        .join(Route, Route.id == DeliveryStop.route_id)
        .filter(
            DeliveryStop.company_id == company_id,
            Route.company_id == company_id,
            Route.route_date == route_date,
            DeliveryStop.tba_numbers.any(needle),
        )
        .first()
    )
    if row is not None:
        stop, route_number = row
        return DuplicateVerdict(
            is_duplicate=True,
            holder_name=stop.walker_name,
            route_number=route_number,
            route_id=stop.route_id,
            basis="delivery_stop",
        )

    return DuplicateVerdict(is_duplicate=False)


# ── write path ────────────────────────────────────────────────────────────────

@dataclass
class IntakeResult:
    """What a completed intake actually did."""
    outcome: str                     # added | removal | needs_dispatch | duplicate
    route_id: Optional[UUID] = None
    route_number: Optional[int] = None
    walker_name: Optional[str] = None
    stop_id: Optional[UUID] = None
    removal_id: Optional[UUID] = None
    reason: Optional[str] = None
    # Set when the package was already registered — the operator is told WHO has
    # it rather than just being refused (ADR-246).
    existing_holder: Optional[str] = None
    existing_route_number: Optional[int] = None


def _merge_stop(stops: list | None, block_key: str, address: str, tba: str) -> list[dict]:
    """Add a package to a stop list, combining with an existing address entry.

    Returns a NEW list of NEW dicts: JSONB columns need reassignment, not
    in-place mutation, for SQLAlchemy change detection. Mirrors _merge_stops in
    walker_routes (ADR-194); reimplemented rather than imported because that
    module is proprietary and this service is public.
    """
    merged = [dict(s) for s in (stops or [])]
    for entry in merged:
        if entry.get("address") == address:
            entry["tba_numbers"] = list(dict.fromkeys(
                (entry.get("tba_numbers") or []) + [tba]
            ))
            return merged
    merged.append({
        "block_key": block_key,
        "address": address,
        "tba_numbers": [tba],
        # Loose find: it rode in someone's tote, so there is no bag of record.
        "bags": [{"bag_id": "(loose)", "bag_color": None, "tba_numbers": [tba]}],
    })
    return merged


def attach_to_route(
    db: Session,
    route: Route,
    *,
    tba: str,
    block_key: Optional[str],
    normalised_address: Optional[str],
    company_id: UUID,
    executor_id: Optional[UUID],
    executor_name: Optional[str],
    recorded_by: UUID,
    recorded_by_name: Optional[str],
):
    """Attach an unregistered package to a route, and open its stop.

    ARRAY and JSONB columns are REASSIGNED rather than appended in place. Since
    ADR-247 Route's columns carry MutableList, so in-place mutation would now
    persist correctly too — but reassignment stays: it is the idiom the rest of
    this file and walker_routes use, and it is the one that keeps working if a
    wrapper is ever dropped. `_merge_stop` returns new dicts for the same reason
    (MutableList does not track mutation of dicts held inside the list).

    Capacity is deliberately NOT checked: the package is already physically in
    the tote, so its capacity was consumed at load. Re-checking capacity_limit
    would apply a planning rule to a fact on the ground (ADR-246).

    Does NOT commit — the caller owns the transaction so the audit row lands
    with the change.
    """
    from app.models.delivery_stop import DeliveryStop

    route.tba_numbers = list(route.tba_numbers or []) + [tba]
    route.package_count = (route.package_count or 0) + 1

    if block_key and block_key not in (route.block_keys or []):
        route.block_keys = list(route.block_keys or []) + [block_key]
    if normalised_address and normalised_address not in (route.normalised_addresses or []):
        route.normalised_addresses = list(route.normalised_addresses or []) + [normalised_address]
    if block_key and normalised_address:
        route.stops = _merge_stop(route.stops, block_key, normalised_address, tba)

    # DeliveryStop is unique on (route_id, normalised_address) — one stop per
    # building per route. A second unregistered package at an address the route
    # already visits joins the EXISTING stop rather than creating a duplicate;
    # inserting blindly raises IntegrityError.
    existing = None
    if normalised_address:
        existing = (
            db.query(DeliveryStop)
            .filter(DeliveryStop.route_id == route.id,
                    DeliveryStop.company_id == company_id,
                    DeliveryStop.normalised_address == normalised_address)
            .first()
        )
    if existing is not None:
        existing.tba_numbers = list(dict.fromkeys(
            list(existing.tba_numbers or []) + [tba]
        ))
        existing.packages_total = (existing.packages_total or 0) + 1
        # A planned stop that gains a found package stays planned; a COMPLETED
        # stop is not reopened — the walker is already past it, and the package
        # needs its own handling rather than a silent revival.
        db.flush()
        return existing

    # is_unplanned=True (ADR-197) is what keeps this out of Amazon
    # reconciliation: the package was never manifested, so counting it in
    # our_delivered would manufacture a discrepancy against ourselves.
    seq = (
        db.query(DeliveryStop)
        .filter(DeliveryStop.route_id == route.id,
                DeliveryStop.company_id == company_id)
        .count()
    ) + 1

    stop = DeliveryStop(
        company_id=company_id,
        route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key=block_key or "UNKNOWN",
        normalised_address=normalised_address,
        tba_numbers=[tba],
        status="planned",
        is_unplanned=True,
        stop_sequence=seq,
        packages_total=1,
        # ADR-244: the route's executor owns the stop; whoever entered it is
        # recorded separately. A dispatcher adding for a walker is exactly the
        # delegated case that ADR fixed.
        walker_id=executor_id,
        walker_name=executor_name,
        recorded_by=recorded_by,
        recorded_by_name=recorded_by_name,
    )
    db.add(stop)
    db.flush()
    return stop


def create_foreign_removal(
    db: Session,
    *,
    company_id: UUID,
    tba: str,
    removal_date: date,
    removed_by: UUID,
    removed_by_name: Optional[str],
    reason: str = "out_of_zone",
):
    """A package that is not ours becomes a PackageRemoval, not a delivery.

    Reuses ADR-176 exactly: persist_zones writes this same row shape for
    out-of-zone packages found at the station. pull_point='anchor_point'
    distinguishes a field find, and the row carries the
    pending -> handed_over -> received custody chain the operator asked for —
    approval is not custody, so the walker->driver->station legs are recorded
    on this row rather than assumed.

    Does NOT commit.
    """
    from app.models.tote_ops import PackageRemoval

    removal = PackageRemoval(
        company_id=company_id,
        removal_date=removal_date,
        bag_id="(loose)",
        tba=tba,
        tba_numbers=None,
        package_count=1,
        whole_tote=False,
        reason=reason,
        status="flagged",
        pull_point="anchor_point",
        removed_by=removed_by,
        removed_by_name=removed_by_name,
        handoff_status="pending",
    )
    db.add(removal)
    db.flush()
    return removal
