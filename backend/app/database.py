import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

DATABASE_URL = settings.database_url

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Yield a database session and close it when the request is done.

    Intended for use as a FastAPI dependency via ``Depends(get_db)``.

    Yields:
        An active SQLAlchemy ``Session`` instance.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── PlaceType (ADR-409) ───────────────────────────────────────────────────────
#
# PlaceType is one product with two datasets — building intelligence and street
# topology (ADR-237 D6) — and its facts are about New York, not about a tenant
# or an environment. Three databases holding three different amounts of the same
# public geography means a route planned in staging traverses a different graph
# than the same route in prod, invisibly, because both look like "the map".
#
# DEFAULTS TO THE APP DATABASE. With PLACETYPE_DATABASE_URL unset this is the
# same engine under a second name, so nothing changes until an environment opts
# in. That is what lets this ship before the grant exists, and what keeps the
# repository clonable with no credential (D4).
_PLACETYPE_URL = os.getenv("PLACETYPE_DATABASE_URL") or DATABASE_URL

placetype_engine = (
    engine if _PLACETYPE_URL == DATABASE_URL
    else create_engine(
        _PLACETYPE_URL,
        # Short timeouts, because a reader that hangs is worse than one that
        # fails: the boundary degrades to an empty map (D4), but only if the
        # call RETURNS. A sort blocked on a dead socket helps nobody.
        connect_args={"connect_timeout": 5},
        pool_pre_ping=True,   # a stale connection to a remote host is normal
        pool_recycle=1800,
    )
)

PlaceTypeSession = sessionmaker(
    autocommit=False, autoflush=False, bind=placetype_engine,
)

#: True when PlaceType is a genuinely separate database. Read by the health
#: check and by tests; NOT by the clients, which must behave identically either
#: way — a reader that branches on this would take an untested path in exactly
#: the deployment that matters.
PLACETYPE_IS_REMOTE = _PLACETYPE_URL != DATABASE_URL


def get_placetype_db():
    """Yield a PlaceType session.

    Separate from `get_db` so the two lifecycles cannot be confused: a tenant
    write and a geography read must never share a transaction once the stores
    are physically apart.
    """
    db = PlaceTypeSession()
    try:
        yield db
    finally:
        db.close()
