"""ADR-288 D1 — a per-truck publish route exists for EVERY truck, not just hubs.

`publish_hub` has no hub-specific logic (not one `is_hub` reference in 252
lines). It was named for hubs because they were the only truck with a per-truck
button. D1 adds a truck-neutral path to the same handler rather than writing a
second one, so the two cannot drift.

Asserted against the OpenAPI SPEC, not `app.routes`: FastAPI >= 0.141 makes
`include_router` lazy, so `app.routes` holds unresolved placeholders and reads
as empty here — the same trap that produced four red CI commits on
test_ui_api_paths_exist.py earlier in this codebase's history.
"""
from app.main import app

_PATHS = set(app.openapi()["paths"])


def test_the_truck_neutral_publish_path_exists():
    assert "/api/v1/dispatch/trucks/{hub_truck_id}/publish" in _PATHS


def test_the_hub_path_is_kept_for_existing_clients():
    """Mobile and the dashboard call /hubs/...; removing it would break them."""
    assert "/api/v1/dispatch/hubs/{hub_truck_id}/publish" in _PATHS


def test_both_are_the_same_operation():
    """Stacked decorators on one function. If these ever became two handlers,
    the per-truck and per-hub publish paths could diverge silently."""
    spec = app.openapi()["paths"]
    truck = spec["/api/v1/dispatch/trucks/{hub_truck_id}/publish"]["post"]
    hub = spec["/api/v1/dispatch/hubs/{hub_truck_id}/publish"]["post"]
    assert truck["requestBody"] == hub["requestBody"]
    assert truck["parameters"] == hub["parameters"]


def test_the_day_level_publish_still_exists():
    """D2 changes its scope, not its existence."""
    assert "/api/v1/dispatch/{dispatch_date}/publish" in _PATHS
