"""The walker's own route in workforce mode: totes, not stops (ADR-297).

Before this, a walker in workforce mode saw NOTHING. Full mode's MyRoute is
served by `walker_routes.py`, registered under `_full_mode`, so every one of its
route reads 404s here.

THE DESIGN PROBLEM, visible in one line of commit-sort:

    normalised_addresses=[],   # addresses stay on ToteAddress (ADR-219)
    stops=None,                # stop granularity does not exist here

Full mode's MyRoute (ADR-149) is built almost entirely from what is missing: a
polled stop list, per-stop complete/RTS actions, a first-stop highlight. Reusing
that screen means reusing a shape whose every element has no data behind it.
"""
import inspect

import pytest

from app.routers import workforce_routes as W
from app.routers.workforce_routes import MyRouteOut, MyRouteToteOut


def _src():
    return inspect.getsource(W.my_route)


# ── D1: a new endpoint, not a mode-branch in the proprietary router ──────────

def test_the_endpoint_lives_on_the_workforce_router():
    """`walker_routes.py` is gated wholesale under `_full_mode`; ungating it to
    serve one read would expose the package-coupled reads beside it."""
    paths = {r.path for r in W.router.routes}
    assert "/workforce/my-route/{entry_date}" in paths


def test_full_modes_my_route_is_untouched():
    """Full mode keeps its own richer screen — this is additive, not a rewrite."""
    import app.main  # noqa: F401
    from app.routers import walker_routes

    assert hasattr(walker_routes, "router")


# ── D2: the caller is the key ────────────────────────────────────────────────

def test_the_route_is_resolved_from_the_CALLER_not_a_path_id():
    """A walker asking "what is my route" must not be able to ask it about
    somebody else. An id in the path is an ownership check waiting to be
    forgotten."""
    params = inspect.signature(W.my_route).parameters
    assert "route_id" not in params
    assert "employee_id" not in params

    src = _src()
    assert "RouteParticipant.employee_id == caller.id" in src
    assert 'RouteParticipant.role == "executor"' in src


def test_both_sides_of_the_join_are_company_scoped():
    """Dimension 1 — the participant side is the easy one to miss."""
    src = _src()
    assert "Route.company_id == caller.company_id" in src
    assert "RouteParticipant.company_id == caller.company_id" in src


def test_gate_reuses_the_existing_field_staff_reader():
    """`_allow_read` is already documented as "field staff read their own
    assignment but never build or assign routes" — precisely this endpoint."""
    gates = [
        getattr(p.default.dependency, "allowed_roles", None)
        for p in inspect.signature(W.my_route).parameters.values()
        if getattr(p.default, "dependency", None) is not None
    ]
    roles = next((g for g in gates if g), [])
    for r in ("walker", "trainee", "trainer"):
        assert r in roles, f"{r} must be able to read their own route"


# ── D3: the TOTE is the unit of work ─────────────────────────────────────────

def test_the_response_is_built_from_totes_not_stops():
    """The inversion from full mode. The captain's entry unit was the tote, the
    sort's input was the tote, and the thing the walker picks up is the tote."""
    f = MyRouteOut.model_fields
    assert "totes" in f
    assert "stops" not in f, "workforce mode has no stop grain — ever"


def test_a_tote_carries_its_colour_for_the_physical_swatch():
    """ADR-296's swatch rules apply unchanged — the walker matches a colour to a
    bag in their hand."""
    f = MyRouteToteOut.model_fields
    assert "bag_color" in f and "bag_color_name" in f
    assert f["bag_color"].default is None, "null renders a neutral pill, not a guess"


def test_block_keys_are_coverage_not_an_itinerary():
    """A list of addresses would imply a delivery sequence we did not compute
    and cannot honour."""
    assert "block_keys" in MyRouteOut.model_fields
    src = _src()
    assert "stop_sequence" not in src
    assert "next-suggestion" not in src


# ── D4: descriptions degrade to the raw key ──────────────────────────────────

def test_descriptions_are_re_derived_from_the_address():
    """The key alone is ambiguous: "100-15 Astoria Blvd" and a Manhattan
    hundred-block both produce Astoria_Blvd_100."""
    assert "describe_stored_block(" in _src()


def test_a_missing_description_falls_back_to_the_raw_key():
    """None is EXPECTED, not exceptional — ADR-219 nulls the address after the
    retention window, so a route read later legitimately has keys and no
    addresses."""
    assert "d or e.block_key" in _src()


# ── D5/D7: what must NOT be in the payload ───────────────────────────────────

def test_package_count_is_absent_from_the_payload_entirely():
    """Not merely hidden by the client. In workforce mode it counts
    captain-entered ADDRESSES; a field that is not in the response cannot be
    rendered by accident."""
    assert "package_count" not in MyRouteOut.model_fields
    assert "flex_package_count" in MyRouteOut.model_fields


def test_no_address_reaches_the_response():
    """Dimension 7, and the dimension most at risk here: the describer takes an
    address as INPUT, so it must not leak out beside its output."""
    for model in (MyRouteOut, MyRouteToteOut):
        for name in model.model_fields:
            assert "address" not in name.lower(), (
                f"{model.__name__}.{name} — addresses are ephemeral (ADR-219)"
            )


def test_no_progress_percentage_is_computed():
    """D5c — a progress bar needs a NUMERATOR, and nothing in workforce mode
    counts deliveries as they happen."""
    src = _src()
    assert "_pct(" not in src
    assert "completion" not in src


def test_flex_count_is_optional_and_defaults_to_none():
    """NULL means "not recorded yet"; 0 means "carried nothing". Conflating them
    is the ADR-294 failure."""
    f = MyRouteOut.model_fields["flex_package_count"]
    assert "Optional" in str(f.annotation)
    assert f.default is None


# ── D6: one shape, including the empty state ─────────────────────────────────

def test_no_route_is_a_flag_not_a_404():
    """A walker with no route is a normal state on a normal day. A 404 forces
    the client to distinguish it from "the endpoint is missing" — the confusion
    RequireMode's 404 already occupies."""
    assert "no_route_assigned" in MyRouteOut.model_fields
    src = _src()
    assert "MyRouteOut(no_route_assigned=True)" in src
    # The empty path must not raise.
    assert "HTTP_404_NOT_FOUND" not in src


def test_the_empty_response_validates_with_no_arguments():
    """One DTO shape either way — every field must be defaulted."""
    out = MyRouteOut(no_route_assigned=True)
    assert out.totes == []
    assert out.flex_package_count is None
    assert out.route_number is None


# ── Cross-ADR: the lifecycle Tier 1 added is visible here ────────────────────

def test_the_walker_sees_the_route_lifecycle():
    """ADR-300 made departed_at/returned_at real. departed set + returned null
    IS "in progress", and the walker's own screen should say so."""
    f = MyRouteOut.model_fields
    assert "departed_at" in f and "returned_at" in f and "status" in f
