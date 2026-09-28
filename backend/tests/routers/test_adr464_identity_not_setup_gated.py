"""Identity endpoints are reachable before setup completes (ADR-464 D1).

The bug: a new Owner landed on Company Setup and the page could not render.
GET /employees/me and /me/mfa-status returned 503 "Company setup is not
complete" -- the condition the page exists to clear. AuthContext calls both on
every authenticated load, so setup was blocked until setup completed.
"""
import inspect
import re

from app.main import _configured
from app.routers import employees as E

IDENTITY_PATHS = {"/employees/me", "/employees/me/mfa-status"}


def _paths(router) -> set[str]:
    return {r.path for r in router.routes}


def test_identity_endpoints_live_on_the_ungated_router():
    assert IDENTITY_PATHS <= _paths(E.identity_router), (
        f"identity_router holds {_paths(E.identity_router)}"
    )


def test_they_are_not_also_on_the_gated_router():
    """Registered twice, the gated copy could still shadow the exempt one."""
    overlap = IDENTITY_PATHS & _paths(E.router)
    assert not overlap, f"{overlap} is still on the configuration-gated router"


def test_the_identity_router_is_mounted_without_the_setup_gate():
    """`dependencies=_configured` on this include would restore the deadlock."""
    src = inspect.getsource(__import__("app.main", fromlist=["main"]))
    line = next(l for l in src.splitlines()
                if "include_router(employees.identity_router" in l)
    assert "_configured" not in line, (
        "the identity router is mounted behind require_configured again"
    )


def test_it_is_mounted_before_the_gated_router():
    """FastAPI matches in registration order: /employees/me would be shadowed
    by the gated router's /employees/{employee_id}."""
    src = inspect.getsource(__import__("app.main", fromlist=["main"]))
    identity = src.index("include_router(employees.identity_router")
    gated = src.index("include_router(employees.router")
    assert identity < gated, "the gated router is registered first and shadows /me"


def test_the_rest_of_the_employees_router_keeps_the_gate():
    """Only identity is exempt. A roster is meaningless before setup, and
    widening the exemption would unpick a deliberate gate."""
    src = inspect.getsource(__import__("app.main", fromlist=["main"]))
    line = next(l for l in src.splitlines()
                if re.search(r"include_router\(employees\.router\b", l))
    assert "_configured" in line, "the employees router lost its setup gate"
    assert _configured, "_configured is empty; the gate is a no-op"


def test_the_setup_page_dependencies_are_the_exempt_ones():
    """Pins WHY these two: AuthContext calls them on every authenticated load,
    including the setup page. If it starts calling a third, this fails."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    ctx = (root / "frontend/src/contexts/AuthContext.tsx").read_text()
    called = set(re.findall(r"get\w*\(\s*'(/employees/[a-z/-]+)'", ctx))
    assert called <= IDENTITY_PATHS, (
        f"AuthContext also calls {called - IDENTITY_PATHS} before setup completes"
    )
