"""ADR-406 — a reserved route is an assigned route whose walker is out.

Behavioural: real tables, the real derivation. The rule is about the interaction
between two routes held by one person, which source text cannot express.
"""
import datetime as dt
import uuid

import pytest

from sqlalchemy import ARRAY as _GA
from sqlalchemy.dialects.postgresql import ARRAY as _PA, JSONB as _JSONB
from sqlalchemy.ext.compiler import compiles as _compiles

# `routes` uses ARRAY and JSONB, neither of which SQLite renders. The same shim
# test_stats_series and test_adr376 use, for the same reason: this suite needs
# the routes table to exist.
for _T in (_GA, _PA, _JSONB):
    _compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")


def _bind(self, dialect):
    import json
    return lambda v: None if v is None else json.dumps(v)


def _result(self, dialect, coltype=None):
    import json

    def p(v):
        if v is None or not isinstance(v, (str, bytes)):
            return v
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return p


# The compiler alone renders the COLUMN as JSON; SQLite still cannot bind a
# Python list as a parameter. These two halves are what test_stats_series uses,
# and both are required.
for _T in (_GA, _PA, _JSONB):
    _T.bind_processor = _bind
    _T.result_processor = _result

from app.models.walker_route import Route, RouteParticipant  # noqa: E402
import app.routers.workforce_routes as W


@pytest.fixture(autouse=True)
def _routes_table(db):
    """`routes` and `route_participants` are not in conftest's DISPATCH_TABLES.

    Created here with checkfirst, the same way test_adr376 does it, rather than
    added to the shared list — adding them there would change the schema every
    other suite builds and turn one fix into a wide breakage.
    """
    # `Route` eager-loads misrouted_package_flags, so selecting a Route needs
    # that table to exist even though nothing here reads it.
    from app.models.walker_route import MisroutedPackageFlag
    for model in (Route, RouteParticipant, MisroutedPackageFlag):
        model.__table__.create(bind=db.get_bind(), checkfirst=True)
    yield


@pytest.fixture()
def ctx():
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), dt.date.today()


def _route(db, cid, ta, day, number, status, walker=None,
           departed=None, returned=None):
    r = Route(company_id=cid, truck_assignment_id=ta, route_date=day,
              route_number=number, status=status, tote_ids=[], block_keys=[],
              package_count=0, slot_cost=2, capacity_limit=12,
              departed_at=departed, returned_at=returned)
    db.add(r)
    db.flush()
    if walker:
        db.add(RouteParticipant(company_id=cid, route_id=r.id,
                                employee_id=walker, role="executor"))
        db.flush()
    return r


class TestTheDerivation:
    def test_assigned_is_reserved_while_its_walker_is_out(self, db, ctx):
        """The rule, directly. Not route numbering: the walker is carrying 7 and
        holding 4, and 4 is the reserved one despite sorting lower."""
        cid, ta, walker, day = ctx
        out = _route(db, cid, ta, day, 7, "in_progress", walker,
                     departed=dt.datetime.now(dt.timezone.utc))
        waiting = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()

        kinds = W._assignment_kind(db, cid, [out, waiting])
        assert kinds.get(waiting.id) == "reserved", (
            "route 4 read as take-it-now while the walker was out with route 7"
        )

    def test_it_flips_to_assigned_when_the_other_route_closes(self, db, ctx):
        """No write to the reserved route. Closing the in-progress one stamps
        returned_at, and the same row now reads assigned because the condition
        that made it reserved is gone — which is why this is derived."""
        cid, ta, walker, day = ctx
        out = _route(db, cid, ta, day, 7, "in_progress", walker,
                     departed=dt.datetime.now(dt.timezone.utc))
        waiting = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [out, waiting])[waiting.id] == "reserved"

        out.status = "completed"
        out.returned_at = dt.datetime.now(dt.timezone.utc)
        db.commit()

        assert W._assignment_kind(db, cid, [out, waiting])[waiting.id] == "assigned", (
            "the reserved route did not become takeable when the walker returned"
        )

    def test_a_free_walkers_route_is_assigned_not_reserved(self, db, ctx):
        cid, ta, walker, day = ctx
        r = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [r])[r.id] == "assigned"

    def test_an_unheld_route_has_no_kind(self, db, ctx):
        """Null, not a default. A route nobody holds is neither."""
        cid, ta, _, day = ctx
        r = _route(db, cid, ta, day, 4, "unassigned")
        db.commit()
        assert W._assignment_kind(db, cid, [r]) == {}

    def test_another_walkers_route_does_not_make_it_reserved(self, db, ctx):
        """The out-route must belong to the SAME person. Keying on 'anyone is
        out' would mark every assigned route on a busy truck as reserved."""
        cid, ta, walker, day = ctx
        other = uuid.uuid4()
        _route(db, cid, ta, day, 7, "in_progress", other,
               departed=dt.datetime.now(dt.timezone.utc))
        mine = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [mine])[mine.id] == "assigned"

    def test_a_returned_route_does_not_reserve(self, db, ctx):
        """departed AND not returned. A closed route leaves the walker free."""
        cid, ta, walker, day = ctx
        now = dt.datetime.now(dt.timezone.utc)
        done = _route(db, cid, ta, day, 7, "completed", walker,
                      departed=now, returned=now)
        waiting = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [done, waiting])[waiting.id] == "assigned"


class TestScoping:
    def test_another_companys_out_route_is_invisible(self, db, ctx):
        """Dim 1. Same employee id under another tenant must not reserve here."""
        cid, ta, walker, day = ctx
        _route(db, uuid.uuid4(), ta, day, 7, "in_progress", walker,
               departed=dt.datetime.now(dt.timezone.utc))
        mine = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [mine])[mine.id] == "assigned"

    def test_yesterdays_out_route_does_not_reserve_today(self, db, ctx):
        """Scoped to the dates in play: an unclosed route from yesterday is a
        data-hygiene problem, not a reason to hold today's work back."""
        cid, ta, walker, day = ctx
        _route(db, cid, ta, day - dt.timedelta(days=1), 7, "in_progress", walker,
               departed=dt.datetime.now(dt.timezone.utc))
        mine = _route(db, cid, ta, day, 4, "assigned", walker)
        db.commit()
        assert W._assignment_kind(db, cid, [mine])[mine.id] == "assigned"
