"""Guard-coverage regression: every mutation endpoint must enforce access.

This is the real security net behind the access-control audit (2026-07-03): the
frontend can only hide buttons; the backend is what actually protects data. A
mutation (POST/PATCH/PUT/DELETE) is "enforced" if EITHER:

  (a) its dependency tree contains a RoleChecker / get_super_admin / secret
      dependency (role-based gate), OR
  (b) it is on OWNERSHIP_ENFORCED — a reviewed allowlist of endpoints that gate
      via an in-body ownership check (caller.id != target -> 403), which
      introspection cannot see.

Any NEW mutation endpoint with neither fails this test until a human classifies
it. That is the point: an unguarded endpoint can never ship silently again
(the /dispatch/manifest gap that this audit found).

Proprietary routers (walker_routes, rts, dispatch, building_profiles, ...) are
absent from the public CI checkout; the test covers whatever routers import.
"""
import importlib

import pytest
from fastapi.routing import APIRoute

from app.api.deps import RoleChecker, get_super_admin

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# Routers to introspect. Proprietary ones are wrapped in try/except at load.
_ROUTER_MODULES = [
    "employees", "trucks", "truck_assignments", "assignment_members",
    "employee_off_days", "employee_relationships", "schedule", "time_off_requests",
    "feedback", "notifications", "continuation_requests", "assignment_change_requests",
    "incidents", "schedule_change_requests", "audit", "trainer_marks",
    "trainer_coverage", "anchor_points", "analytics", "shift_ops", "companies",
    "internal", "shift_sessions", "sort", "graduation_quiz", "gear_requests",
    "trainee_credentials", "truck_transfers", "driver_surveys", "adp",
    "building_profiles", "building_profile_library", "walker_routes", "rts",
    "roll_call",
]

# Reviewed 2026-07-03: mutation endpoints enforced by an IN-BODY ownership check
# (caller.id / token), not a RoleChecker dependency. Each verified to raise 403
# for non-owners. Key = "METHOD path". Adding here is a conscious security review.
OWNERSHIP_ENFORCED = {
    "POST /employee-off-days/",                                # caller.id == employee_id
    "POST /time-off-requests/",                                # caller.id == employee_id
    "DELETE /time-off-requests/{request_id}",                  # owns request
    "POST /schedule-change-requests/",                         # caller.id == employee_id
    "DELETE /schedule-change-requests/{request_id}",           # owns request
    "POST /feedback/",                                         # submits as caller
    "POST /incidents/",                                        # reporter = caller
    "PATCH /notifications/{notification_id}/read",             # owns notification
    "PATCH /notifications/employee/{employee_id}/read-all",    # caller.id == employee_id
    "POST /employees/me/email/confirm-change",                 # token/code = auth
    "POST /employees/me/discord/confirm-link",                 # DM code = auth (ADR-270)
    "DELETE /employee-relationships/{employee_relationship_id}",  # owns relationship
    "POST /adp/adjustments/{adjustment_id}/employee-signoff",  # caller.id == employee_id
    "POST /adp/adjustments/{adjustment_id}/reject",            # caller on record or admin
}


def _has_guard_dependency(route: APIRoute) -> bool:
    found = False

    def walk(dep):
        nonlocal found
        call = getattr(dep, "call", None)
        if isinstance(call, RoleChecker) or call is get_super_admin:
            found = True
        elif call is not None and getattr(call, "__name__", "") == "_verify_secret":
            found = True
        for sub in getattr(dep, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    return found


def _all_mutation_routes():
    routes = []
    for name in _ROUTER_MODULES:
        try:
            mod = importlib.import_module(f"app.routers.{name}")
        except Exception:
            continue  # proprietary / optional router absent in this env
        for attr in ("router", "company_admin_router"):
            router = getattr(mod, attr, None)
            if router is None:
                continue
            for r in router.routes:
                if isinstance(r, APIRoute) and (r.methods & WRITE_METHODS):
                    method = sorted(r.methods & WRITE_METHODS)[0]
                    routes.append((name, method, r.path, r))
    return routes


def test_every_mutation_endpoint_is_enforced():
    """No mutation endpoint may ship without a role guard OR a reviewed
    ownership-enforcement entry."""
    unenforced = []
    for name, method, path, route in _all_mutation_routes():
        if _has_guard_dependency(route):
            continue
        if f"{method} {path}" in OWNERSHIP_ENFORCED:
            continue
        unenforced.append(f"{name}: {method} {path}")

    assert not unenforced, (
        "Mutation endpoint(s) with no role guard and not on the reviewed "
        "OWNERSHIP_ENFORCED allowlist — add a RoleChecker, or verify the in-body "
        "ownership check and add it to the allowlist:\n  "
        + "\n  ".join(sorted(unenforced))
    )


def test_ownership_allowlist_has_no_stale_entries():
    """Every OWNERSHIP_ENFORCED entry must still correspond to a real,
    non-role-guarded route — so the allowlist can't rot into a rubber stamp."""
    present = {
        f"{method} {path}"
        for _, method, path, route in _all_mutation_routes()
        if not _has_guard_dependency(route)
    }
    # Only assert for entries whose router is actually loaded in this env.
    loaded_prefixes = {
        path.split("/")[1] for _, _, path, _ in _all_mutation_routes() if "/" in path
    }
    checkable = {
        e for e in OWNERSHIP_ENFORCED
        if e.split(" ", 1)[1].split("/")[1] in loaded_prefixes
    }
    stale = checkable - present
    assert not stale, (
        "OWNERSHIP_ENFORCED entries that are now role-guarded or gone — remove "
        f"them:\n  " + "\n  ".join(sorted(stale))
    )
