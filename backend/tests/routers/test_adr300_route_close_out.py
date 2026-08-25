"""The workforce route lifecycle: depart, close, and who may be given a route (ADR-300).

Before this, nothing in workforce mode advanced a route past `assigned`.
Verified on staging: 46,889 routes, 1 with `departed_at`, 0 with `returned_at`.
A workforce day had no ending — returns were recorded against routes that never
closed, and no moment made the day's numbers final.

THE STAMPS ARE NOT INSTRUMENTATION. `departed_at` set with `returned_at` NULL
IS "in progress", and that is what lets a captain hand out a SECOND route once
the first is done. The metrics in ADR-298 are a by-product of getting the
lifecycle right, not its purpose.
"""
import inspect

import pytest

from app.routers import workforce_routes as W


def _src(fn):
    return inspect.getsource(fn)


# ── D1: the captain closes it, at the truck ──────────────────────────────────

def test_close_is_route_lead_gated_not_walker_facing():
    """A walker self-closing from the field would settle the route before the
    packages are physically accounted for — the one thing the close prevents."""
    gates = [
        getattr(p.default.dependency, "allowed_roles", None)
        for p in inspect.signature(W.close_route).parameters.values()
        if getattr(p.default, "dependency", None) is not None
    ]
    roles = next((g for g in gates if g), [])
    assert "walker" not in roles
    assert "captain" in roles or "driver" in roles


def test_close_checks_truck_membership():
    """Object-level ownership: a captain closes routes on THEIR truck only."""
    assert "_assert_truck_member" in _src(W.close_route)


# ── D2: the two stamps, and what they mean ───────────────────────────────────

def test_close_sets_completed_and_returned_together():
    """Workforce mode has no stop grain, so "work finished" has no signal of its
    own. The only observable event is the walker standing at the truck."""
    src = _src(W.close_route)
    assert 'route.status = "completed"' in src
    assert "route.returned_at = datetime.now(timezone.utc)" in src


def test_departure_is_stamped_when_it_happens_never_back_filled():
    """Back-filling at close would fabricate a duration."""
    depart = _src(W.depart_route)
    assert "route.departed_at = datetime.now(timezone.utc)" in depart
    assert 'route.status = "in_progress"' in depart
    # The close must not touch departed_at at all.
    assert "route.departed_at =" not in _src(W.close_route)


def test_departed_plus_unreturned_is_the_in_progress_signal():
    """The pair IS the lifecycle — asserted where it is consumed (D2b)."""
    src = _src(W.assign_walker)
    assert "Route.departed_at.isnot(None)" in src
    assert "Route.returned_at.is_(None)" in src


# ── D2b: a walker who is out cannot be given another route ───────────────────

def test_assign_refuses_a_walker_who_is_still_out():
    """THE gap this ADR closes.

    `assign_walker` guarded the ROUTE ("this route is already out") but never
    the WALKER — zero queries of the assignee's other routes. A captain could
    hand a second route to someone still walking their first.
    """
    src = _src(W.assign_walker)
    assert "RouteParticipant.employee_id == walker.id" in src
    assert "HTTP_409_CONFLICT" in src


def test_the_busy_409_names_the_route_they_are_on():
    """"This walker is busy" is useless without "...on route 4"."""
    src = _src(W.assign_walker)
    assert "busy.route_number" in src


def test_busy_check_is_scoped_to_the_same_day():
    """Yesterday's unclosed route is a data-hygiene problem, not a reason to
    block today's assignment."""
    src = _src(W.assign_walker)
    assert "Route.route_date == route.route_date" in src


def test_busy_check_excludes_the_route_being_assigned():
    """Re-assigning the SAME route must not report the walker as busy on it."""
    assert "Route.id != route.id" in _src(W.assign_walker)


# ── D3: one-way stamps ───────────────────────────────────────────────────────

def test_closing_twice_is_a_409():
    """Per CLAUDE.md dim 2, and matching full mode's back-at-truck guard.
    Re-closing must not re-open a settled number."""
    src = _src(W.close_route)
    assert "route.returned_at is not None" in src
    assert "HTTP_409_CONFLICT" in src


def test_departing_twice_is_a_409():
    """Re-tapping must not move the clock."""
    src = _src(W.depart_route)
    assert "route.departed_at is not None" in src
    assert "HTTP_409_CONFLICT" in src


def test_a_completed_route_cannot_be_departed():
    """The status gate, not just the timestamp gate."""
    assert 'route.status != "assigned"' in _src(W.depart_route)


# ── D4: a clean route closes without ceremony ────────────────────────────────

def test_close_does_not_require_any_returns():
    """A clean route is a real and common outcome. The CLIENT prompts for
    returns; the endpoint must not demand a non-empty list."""
    sig = inspect.signature(W.close_route)
    body_params = [
        p for p in sig.parameters.values()
        if getattr(p.default, "dependency", None) is None
        and p.name not in ("route_id", "caller", "db", "_")
    ]
    assert body_params == [], "close takes no body — returns are recorded separately"


# ── D5: the close freezes the package count ──────────────────────────────────

def test_flex_count_is_frozen_once_the_route_closes():
    """Until the close it is deliberately re-recordable; afterwards it is the
    day's persisted record (ADR-299 D4)."""
    src = _src(W.record_flex_package_count)
    assert "route.returned_at is not None" in src
    assert "HTTP_409_CONFLICT" in src


def test_the_close_audits_the_number_it_froze():
    """NULL is recorded as NULL — never as 0, which would read as "carried
    nothing" rather than "never scanned"."""
    src = _src(W.close_route)
    assert '"flex_package_count": route.flex_package_count' in src
    assert "workforce_route.closed" in src


# ── Cross-ADR: the lifecycle is what arms 298 and 302 ────────────────────────

def test_closing_produces_the_state_adr302_protects():
    """A closed route is `completed`, which the re-sort allow-list must never
    delete. If this pair ever disagreed, a re-sort would destroy closed days."""
    from app.services.constants import DELETABLE_ON_RESORT

    assert 'route.status = "completed"' in _src(W.close_route)
    assert "completed" not in DELETABLE_ON_RESORT


def test_closing_produces_the_state_adr298_guards_against():
    """`returned_at` is what ADR-298's dashboard blocks filter on. Before this
    endpoint they returned nothing; now they must be mode-gated instead."""
    from app.services.dashboard_summaries import _route_package_metrics_available

    assert "route.returned_at = datetime.now(timezone.utc)" in _src(W.close_route)
    assert callable(_route_package_metrics_available)
