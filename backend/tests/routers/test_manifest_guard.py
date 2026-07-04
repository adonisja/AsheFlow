"""Regression: package-manifest mutations must carry a role guard (access audit).

POST /dispatch/manifest and PATCH /dispatch/manifest/{truck_id} previously had
only get_caller_employee + company scoping — any authenticated employee could
create/edit a manifest, which is a dispatch operation. This asserts both
endpoints declare the allow_dispatch_mgmt RoleChecker dependency so the guard
cannot silently regress.
"""
from fastapi.routing import APIRoute

from app.routers.dispatch import router, allow_dispatch_mgmt


def _route(path: str, method: str) -> APIRoute:
    for r in router.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            return r
    raise AssertionError(f"route {method} {path} not found")


def _has_dispatch_mgmt_guard(route: APIRoute) -> bool:
    # RoleChecker instances are the .dependency callables on the route.
    return any(dep.call is allow_dispatch_mgmt for dep in route.dependant.dependencies)


def test_create_manifest_is_dispatch_guarded():
    assert _has_dispatch_mgmt_guard(_route("/dispatch/manifest", "POST"))


def test_update_manifest_is_dispatch_guarded():
    assert _has_dispatch_mgmt_guard(_route("/dispatch/manifest/{truck_id}", "PATCH"))
