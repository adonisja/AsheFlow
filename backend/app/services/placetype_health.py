"""Is PlaceType reachable, and does it hold anything? (ADR-409)

A THIRD module, deliberately. `health()` first lived in `segment_map`, and the
ADR-237 boundary test rejected it twice in one run:

  - it imported `BuildingProfileLibrary`, and only `library/client` may;
  - it named `PLACETYPE_IS_REMOTE`, and no reader may branch on the transport.

Both were right. A health check spans BOTH datasets — that is what makes it a
health check for the product rather than for one table — so it cannot live
inside either client without breaking the ownership rule each client enforces.

It is not a reader. Nothing routes on it, so it may know things the readers must
not: which transport is configured, and whether the store answered at all.
"""
from __future__ import annotations

from sqlalchemy.exc import InterfaceError, OperationalError


def health() -> dict:
    """Reported, never enforced.

    An empty or unreachable PlaceType is a DEGRADED sort, not a broken one —
    production runs with zero segments today and sorts fine. This exists to make
    that degradation visible instead of silent.

    Uses its own session rather than accepting one: the point is to test the
    CONNECTION, and a session handed in has already proven one exists.
    """
    from app.database import PLACETYPE_IS_REMOTE, PlaceTypeSession
    from app.models.building_profile_library import BuildingProfileLibrary
    from app.models.street_segment import StreetSegment

    out: dict = {
        "remote": PLACETYPE_IS_REMOTE,
        "reachable": False,
        "segments": None,
        "buildings": None,
    }
    db = PlaceTypeSession()
    try:
        out["segments"] = db.query(StreetSegment).count()
        out["buildings"] = db.query(BuildingProfileLibrary).count()
        out["reachable"] = True
    except (OperationalError, InterfaceError) as exc:
        # The same two errors the readers degrade on, for the same reason: an
        # outage is reported, a bug still raises.
        out["error"] = type(exc).__name__
    finally:
        db.close()
    return out
