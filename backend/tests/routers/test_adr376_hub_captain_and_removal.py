"""A hub needs no captain, and a finalized hub cannot be removed (ADR-376).

Two hub-shaped gaps reported together.

1. After posting the hub's final crew the board warned:

       NO CAPTAIN ON 1 TRUCK
       Crews were posted anyway. Assign a captain, or elevate an unpaired
       trainer: Hub

   ADR-274 D10 settled this the other way: "a hub has no captain, so the DRIVER
   leads". The warning asked the dispatcher to fix something correct by design.

   ADR-375 D4 already excluded hubs from the DAY-WIDE finalize gate, and the
   captain check reads that same list -- so the day-wide path was right. This
   fired on the PER-TRUCK path, where ADR-375 deliberately leaves the list
   unnarrowed so a hub finalized by name still gates on its own confirmations.
   Right for the confirmation rate, wrong for the captain check: two guards
   sharing one loop, answering two different questions.

2. `remove_hub` computed `was_published` for its audit row and never gated on
   it, so a hub whose final crew was already posted to Discord deleted silently,
   taking its members and routes with it. `publish_hub` already refuses a
   completed assignment one endpoint away.
"""
import asyncio
import datetime
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from sqlalchemy import ARRAY as _GA
from sqlalchemy.dialects.postgresql import ARRAY as _PA, JSONB as _JSONB
from sqlalchemy.ext.compiler import compiles as _compiles

# `routes` uses ARRAY and JSONB, neither of which SQLite renders. Same shim
# test_stats_series.py uses, for the same reason: remove_hub deletes the
# assignment's routes, so the table has to exist to test the guard in front of
# that delete.
for _T in (_GA, _PA, _JSONB):
    _compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")

from app.models.assignment_member import AssignmentMember
from app.models.dispatch_confirmation import DispatchConfirmation
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.routers import dispatch as D
from tests.conftest import SEED_COMPANY_ID, make_employee, make_truck

DAY = datetime.date(2026, 9, 4)


@pytest.fixture(autouse=True)
def _routes_table(db):
    """remove_hub deletes the assignment's routes, so the table must exist.

    Created on THIS session's engine rather than added to conftest's shared
    DISPATCH_TABLES: a partial `routes` mirror there shadowed the real model for
    every other suite that builds its own engine from `Route.__table__`
    (test_stats_series and friends), turning one fix into 64 failures.
    """
    from app.models.walker_route import Route
    Route.__table__.create(bind=db.get_bind(), checkfirst=True)
    yield


def _truck(db, name, is_hub=False):
    t = make_truck(db, name)
    t.is_hub = is_hub
    db.commit()
    return t


def _assignment(db, truck, status="active"):
    a = TruckAssignment(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID,
        truck_id=truck.id, date=DAY, status=status,
    )
    db.add(a)
    db.commit()
    return a


def _member(db, assignment, emp, role, confirmed=True):
    """Seat someone, confirmed by default.

    The ADR-205 50% gate 409s before the captain check is ever reported, so an
    unconfirmed crew would make these tests fail for a reason that has nothing
    to do with captains.
    """
    m = AssignmentMember(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID,
        assignment_id=assignment.id, employee_id=emp.id, role=role,
    )
    db.add(m)
    if confirmed:
        db.add(DispatchConfirmation(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID,
            employee_id=emp.id, date=DAY, status="confirmed", source="app",
        ))
    db.commit()
    return m


def _finalize(db, caller, truck_id=None):
    """Run finalize with the Discord webhook stubbed (see test_finalize_gate).

    finalize posts to the bot BEFORE returning, so a test that inspects the
    RESPONSE dies on a real connection to bot:8001. The stub shape is copied
    from test_finalize_gate._run_past_bot rather than reinvented.
    """
    class _Resp:
        status = 200
        async def text(self): return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Sess:
        def post(self, *a, **k): return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    with patch("app.routers.dispatch.aiohttp.ClientSession", lambda *a, **k: _Sess()):
        return asyncio.run(D.finalize_dispatch(
            dispatch_date=DAY, truck_id=truck_id, db=db, caller=caller, _=None,
        ))


class TestTheCaptainWarningSkipsHubs:
    def test_a_hub_finalized_by_name_does_not_warn_about_a_captain(self, db):
        """The reported case: 'Post Hub Final Crew' on a driver-led hub.

        finalize_dispatch is async, so it MUST be awaited -- calling it bare
        returns a coroutine that never runs and asserts nothing.
        """
        hub = _truck(db, "Hub", is_hub=True)
        a = _assignment(db, hub)
        _member(db, a, make_employee(db, "driver", "Danny Driver"), "driver")
        _member(db, a, make_employee(db, "trainer", "Jerome Whitfield"), "trainer")

        out = _finalize(db, make_employee(db, "dispatch", "Dispatcher"), truck_id=hub.id)

        assert out["captainless_trucks"] == [], (
            f"a hub has no captain by design (ADR-274 D10); warning about it "
            f"asks dispatch to fix something correct. Got: "
            f"{out['captainless_trucks']}"
        )

    def test_a_regular_truck_finalized_by_name_still_warns(self, db):
        """The exclusion must be about hub-ness, not about the per-truck path."""
        atlas = _truck(db, "Atlas", is_hub=False)
        a = _assignment(db, atlas)
        _member(db, a, make_employee(db, "driver", "Hayden King"), "driver")

        out = _finalize(db, make_employee(db, "dispatch", "Dispatcher"), truck_id=atlas.id)

        assert out["captainless_trucks"] == ["Atlas"], (
            "a regular truck with no captain must still be named (ADR-256 D3)"
        )

    def test_a_day_wide_finalize_names_only_the_regular_truck(self, db):
        """Both guards at once: hub excluded, regular truck still reported."""
        hub = _truck(db, "Hub", is_hub=True)
        atlas = _truck(db, "Atlas", is_hub=False)
        ha = _assignment(db, hub)
        aa = _assignment(db, atlas)
        _member(db, ha, make_employee(db, "driver", "Danny"), "driver")
        _member(db, aa, make_employee(db, "driver", "Hayden"), "driver")

        out = _finalize(db, make_employee(db, "dispatch", "Dispatcher"), truck_id=None)

        assert out["captainless_trucks"] == ["Atlas"], (
            f"only the regular truck should be named, got "
            f"{out['captainless_trucks']}"
        )

    def test_a_regular_truck_with_no_captain_still_warns(self, db):
        """The guard must not have disabled the warning outright."""
        import inspect
        src = inspect.getsource(D.finalize_dispatch)
        assert "captainless_trucks.append" in src
        assert "a.truck_id not in hub_ids" in src, (
            "the captain check lost its hub exclusion"
        )

    def test_hub_ids_is_resolved_on_both_call_paths(self, db):
        """The bug was hub_ids existing only under `if truck_id is None`."""
        import inspect
        src = inspect.getsource(D.finalize_dispatch)
        i_hub = src.index("hub_ids = {")
        i_if = src.index("if truck_id is None:")
        assert i_hub < i_if, (
            "hub_ids must be resolved BEFORE the day-wide narrowing, or the "
            "captain check cannot see it on the per-truck path"
        )

    def test_the_confirmation_gate_keeps_its_adr375_scoping(self, db):
        """D1 must not weaken ADR-375: a hub finalized BY NAME still gates on
        its own confirmations. Only the captain question is unconditional."""
        import inspect
        src = inspect.getsource(D.finalize_dispatch)
        assert "gating = [a for a in assignments if a.truck_id not in hub_ids]" in src
        assert "if truck_id is None:" in src
        assert "for a in gating:" in src


class TestAFinalizedHubCannotBeRemoved:
    def _call(self, db, truck, caller):
        return D.remove_hub(
            hub_truck_id=truck.id, target_date=DAY,
            db=db, caller=caller, _=None,
        )

    def test_a_completed_hub_is_refused(self, db):
        hub = _truck(db, "Hub", is_hub=True)
        a = _assignment(db, hub, status="completed")
        _member(db, a, make_employee(db, "driver", "Danny"), "driver")
        caller = make_employee(db, "dispatch", "Dispatcher")

        with pytest.raises(HTTPException) as exc:
            self._call(db, hub, caller)
        assert exc.value.status_code == 409
        assert "final crew" in exc.value.detail

    def test_the_refusal_leaves_the_assignment_and_crew_intact(self, db):
        """A refused delete must be a no-op, not a partial one."""
        hub = _truck(db, "Hub", is_hub=True)
        a = _assignment(db, hub, status="completed")
        _member(db, a, make_employee(db, "driver", "Danny"), "driver")
        caller = make_employee(db, "dispatch", "Dispatcher")

        with pytest.raises(HTTPException):
            self._call(db, hub, caller)

        assert db.query(TruckAssignment).filter(
            TruckAssignment.id == a.id).first() is not None
        assert db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == a.id).count() == 1

    @pytest.mark.parametrize("status", ["planned", "active"])
    def test_removal_before_finalize_still_works(self, status, db):
        """ADR-274 D8 is unchanged for the states its reasoning covers."""
        hub = _truck(db, "Hub", is_hub=True)
        a = _assignment(db, hub, status=status)
        _member(db, a, make_employee(db, "driver", "Danny"), "driver")
        caller = make_employee(db, "dispatch", "Dispatcher")

        self._call(db, hub, caller)

        assert db.query(TruckAssignment).filter(
            TruckAssignment.id == a.id).first() is None, (
            f"a {status} hub must still be removable (ADR-274 D8)"
        )

    def test_the_guard_matches_the_publish_hub_precedent(self, db):
        """Same object, same state, same refusal -- one endpoint away."""
        import inspect
        assert 'assignment.status == "completed"' in inspect.getsource(D.remove_hub)
        assert 'assignment.status == "completed"' in inspect.getsource(D.publish_hub)


class TestTheFrontendHidesTheControl:
    """The server guard is the enforcement; this is so the dispatcher never
    aims at a button that cannot work (ADR-376 D3)."""

    def test_remove_is_hidden_once_the_final_crew_is_posted(self):
        from pathlib import Path
        dash = (Path(__file__).resolve().parents[2].parent
                / "frontend" / "src" / "pages" / "DispatchDashboard.tsx")
        src = dash.read_text(encoding="utf-8")
        assert "{isHub && st !== 'completed' && (" in src, (
            "the Remove control must be hidden on a completed hub"
        )
