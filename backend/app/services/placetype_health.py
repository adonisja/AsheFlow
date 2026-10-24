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

from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError


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
        # ADR-583 D4: the API's role must be SELECT-only. None = not checked
        # (PlaceType shares the app database, so the grant does not exist yet).
        "writable": None,
    }
    db = PlaceTypeSession()
    try:
        out["segments"] = db.query(StreetSegment).count()
        out["buildings"] = db.query(BuildingProfileLibrary).count()
        out["reachable"] = True
        if PLACETYPE_IS_REMOTE:
            out["writable"] = _can_write(db)
    except (OperationalError, InterfaceError) as exc:
        # The same two errors the readers degrade on, for the same reason: an
        # outage is reported, a bug still raises.
        out["error"] = type(exc).__name__
    finally:
        db.close()
    return out


def _can_write(db) -> bool:
    """ADR-583 D4. Attempt one INSERT and roll it back. A SELECT-only role is
    refused with a permission error (ProgrammingError); anything that inserts
    means the grant is wrong. Never commits, so a writable role leaves no row."""
    try:
        db.execute(text(
            "INSERT INTO street_segments (id, segment_id, source) "
            "VALUES (gen_random_uuid(), '__adr583_write_probe__', 'probe')"))
    except ProgrammingError:
        db.rollback()
        return False
    db.rollback()
    return True
