"""The ONLY module in AsheFlow that reads PlaceType building tables (ADR-237 D1).

The Library is named **PlaceType** (ADR-237 D6): one product, two datasets —
building intelligence (this client) and street topology (`services/segment_map`).
The package is still `app.library` on purpose; renaming an internal module ahead
of the physical split (D3) would churn imports for no boundary gain.

WHY THIS EXISTS
---------------
The Library is on its way to being an independently-owned product that AsheFlow
consumes (ADR-237). This module is the boundary that makes that move mechanical
rather than a rewrite: every reader goes through it, so the eventual physical
split changes ONE implementation instead of five call sites.

It is deliberately a LOGICAL split first — same repository, same database, same
deployment (ADR-237 D4). Nothing ships anywhere yet. The models could already
move (they import only `Base`), but the promotion router still reads tenant
`BuildingProfile` data, and relocating code before that seam is designed would
move the coupling rather than remove it.

THE RULE THIS ENFORCES
----------------------
`library_status == "active"` was repeated at all five call sites. A single
missed filter would silently serve deprecated building intelligence into
routing — no error, just worse routes. It now lives in one place and cannot be
forgotten.

WHAT BELONGS HERE
-----------------
Reads of `BuildingProfileLibrary` — the building-intelligence half.

NOT `BuildingProfile`, which is tenant-owned, `company_id`-scoped, and stays in
AsheFlow (ADR-237 audit note, dimension 1). Callers merge the two tiers
themselves; this module never sees a `company_id` and never returns tenant data.

NOT `StreetSegment` either, and deliberately so. ADR-237 D2 asks for topology to
sit behind the same boundary — it already does: `services/segment_map.py` owns
every read and write of that table, and its four consumers go through it rather
than importing the model. Re-routing it through here would add a hop without
adding containment. What D2 actually needs is the OWNERSHIP note, not a move;
`segment_map` is the topology client, this is the building-intelligence one.

WRITES ARE NOT HERE
-------------------
Promotion, conflict resolution and deprecation stay in
`routers/building_profile_library.py`, which is the surface that transfers to
the Library owner. Under D5, AsheFlow will PUSH nominations rather than write
directly.
"""
from __future__ import annotations

import functools
import logging
from typing import Iterable, Optional

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.models.building_profile_library import BuildingProfileLibrary

logger = logging.getLogger(__name__)

# The one invariant every read shares. Deprecated and conflicted rows exist in
# the table and must never reach routing.
_ACTIVE = "active"


def _degrades_to(empty):
    """Turn an UNREACHABLE PlaceType into an EMPTY one (ADR-409 D4).

    An empty Library is already proven safe — production runs with zero rows
    today and sorts fine, because routing falls back to same-street and parallel
    edges (ADR-291). An unreachable one was NOT: every reader here calls through
    a Session with no guard, so a connection failure raised and failed the whole
    sort.

    Those two cases are indistinguishable today only because the Library shares
    AsheFlow's database. ADR-409 D1 moves it, which makes the distinction real —
    so this guard is a PREREQUISITE of that move, not a follow-up. Without it,
    a network blip becomes a failed sort for every tenant.

    Degrading at the BOUNDARY rather than at each call site is the property
    ADR-237 D1 built this module to make possible: one place to change when the
    transport becomes remote.

    Deliberately narrow: OperationalError (the connection dropped, the host is
    unreachable) and InterfaceError (the connection was already closed). A
    ProgrammingError from a bad query is a bug in this module and must still
    raise, or a schema mistake would silently route every tenant on the fallback
    graph forever.

    NOT `DBAPIError` — it is the PARENT of ProgrammingError as well, so catching
    it swallows exactly the bugs this comment says must escape. Caught by a test
    that asserts a ProgrammingError still propagates.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (OperationalError, InterfaceError) as exc:
                # No stack trace and no exception text: this is an expected
                # degradation, and a traceback per sort would bury real errors.
                logger.warning(
                    "placetype_unreachable: %s degraded to empty; routing on the "
                    "fallback graph (%s)", fn.__name__, type(exc).__name__,
                )
                return empty() if callable(empty) else empty
        return wrapper
    return decorate


@_degrades_to(list)
def all_active(db: Session) -> list[BuildingProfileLibrary]:
    """Every active Library record.

    The hot path (`run_sort._get_workload_dicts`) calls this ONCE per sort and
    builds a dict, rather than looking up per package. That is what makes an
    eventually-remote Library affordable: one fetch per sort, cacheable, with no
    network hop in the per-package path (ADR-237, measured coupling).

    Do not change this to a per-address query without re-reading that note.
    """
    return (
        db.query(BuildingProfileLibrary)
        .filter(BuildingProfileLibrary.library_status == _ACTIVE)
        .all()
    )


@_degrades_to(None)
def by_address(db: Session, normalised_address: str) -> Optional[BuildingProfileLibrary]:
    """One active Library record, or None.

    Tier 2 of the lookup chain: callers try their own tenant `BuildingProfile`
    first and fall back here for cold-start coverage.
    """
    return (
        db.query(BuildingProfileLibrary)
        .filter(
            BuildingProfileLibrary.normalised_address == normalised_address,
            BuildingProfileLibrary.library_status == _ACTIVE,
        )
        .first()
    )


@_degrades_to(dict)
def by_addresses(
    db: Session, normalised_addresses: Iterable[str]
) -> dict[str, BuildingProfileLibrary]:
    """Active Library records for a set of addresses, keyed by address.

    Returns {} for an empty input WITHOUT querying — an unguarded `.in_([])`
    is a full-table scan on some backends and a silent empty result on others,
    and the call sites already had to remember that guard themselves.
    """
    addresses = list(normalised_addresses)
    if not addresses:
        return {}
    return {
        row.normalised_address: row
        for row in db.query(BuildingProfileLibrary)
        .filter(
            BuildingProfileLibrary.normalised_address.in_(addresses),
            BuildingProfileLibrary.library_status == _ACTIVE,
        )
        .all()
    }
