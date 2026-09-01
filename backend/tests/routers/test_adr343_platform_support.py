"""Support can diagnose without being able to break a tenant (ADR-343).

`super_admin` was the only platform group and gated all 17 platform endpoints —
12 writes including deactivate_company, set_operating_mode and
bootstrap_company_admin, alongside the 5 reads support actually needs. Anyone
onboarded to investigate an issue could also take a customer offline.
"""
import ast
import inspect
import os

import pytest

from app.api import deps as D

ROUTERS = (
    "app/routers/companies.py",
    "app/routers/platform_alerts.py",
    "app/routers/building_profile_library.py",
)

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")


def _endpoints():
    """(name, http_method, gate) for every platform endpoint."""
    out = []
    for rel in ROUTERS:
        path = os.path.abspath(os.path.join(BACKEND, rel))
        tree = ast.parse(open(path).read())
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            deco = " ".join(ast.unparse(d) for d in n.decorator_list)
            if "router." not in deco:
                continue
            sig = ast.unparse(n.args)
            gate = ("platform_staff" if "get_platform_staff" in sig
                    else "super_admin" if "get_super_admin" in sig else None)
            if gate is None:
                continue
            method = ("GET" if ".get(" in deco else "POST" if ".post(" in deco
                      else "PUT" if ".put(" in deco else "PATCH" if ".patch(" in deco
                      else "DELETE")
            out.append((n.name, method, gate))
    return out


# ── Dim 2: THE invariant ─────────────────────────────────────────────────────

def test_no_write_endpoint_accepts_the_weaker_group():
    """The whole point. A write reachable by `platform_support` means support can
    deactivate a company — and that regression is invisible in review, because
    it looks like one more endpoint using the shared dependency."""
    weak_writes = [
        (n, m) for n, m, g in _endpoints()
        if g == "platform_staff" and m != "GET"
    ]
    assert not weak_writes, (
        f"these WRITE endpoints accept platform_support: {weak_writes}"
    )


def test_the_dangerous_writes_are_still_super_admin_only():
    """Named explicitly, because these three can take a tenant offline or hand
    someone administrative control of it."""
    gates = {n: g for n, _m, g in _endpoints()}
    for fn in ("deactivate_company", "set_operating_mode", "bootstrap_company_admin"):
        assert gates.get(fn) == "super_admin", f"{fn} is not super-admin-only"


def test_reads_are_reachable_by_support():
    """Otherwise the group exists and grants nothing."""
    gates = {n: g for n, _m, g in _endpoints()}
    for fn in ("list_companies", "get_company", "list_platform_alerts"):
        assert gates.get(fn) == "platform_staff", f"{fn} is not support-readable"


def test_every_platform_endpoint_has_one_of_the_two_gates():
    """An ungated platform endpoint is worse than a wrongly-gated one."""
    eps = _endpoints()
    assert len(eps) >= 17, f"expected >=17 platform endpoints, found {len(eps)}"
    assert all(g in ("platform_staff", "super_admin") for _n, _m, g in eps)


# ── D3: the one judgement call ───────────────────────────────────────────────

def test_resolving_an_alert_stays_super_admin_only():
    """ADR-335 D3 — alerts resolve THEMSELVES when the condition ends, so a
    human resolve asserts "I have decided this is over", which is a claim about
    infrastructure. Support seeing a board they cannot dismiss is correct."""
    gates = {n: g for n, _m, g in _endpoints()}
    assert gates.get("resolve_platform_alert") == "super_admin"


# ── D1: the dependency itself ────────────────────────────────────────────────

def test_the_dependency_accepts_either_platform_group():
    src = inspect.getsource(D.get_platform_staff)
    assert "PLATFORM_GROUPS" in src
    assert D.PLATFORM_GROUPS == frozenset({"super_admin", "platform_support"})


def test_a_super_admin_keeps_every_permission():
    """Nothing is taken away — super_admin is in the accepted set, so the reads
    it could do before it can still do."""
    assert "super_admin" in D.PLATFORM_GROUPS


def test_it_never_touches_the_employee_table():
    """A platform user belongs to no company, and Employee.company_id is
    nullable=False — a row would force an arbitrary tenant and inherit its
    scoping everywhere (same constraint as ADR-335 and ADR-274 D13)."""
    # Docstrings stripped: this function's own docstring explains that it does
    # NOT touch the Employee table, which a raw grep matches. Eleventh
    # prose-vs-code false positive of this stretch.
    tree = ast.parse(inspect.getsource(D.get_platform_staff))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body.pop(0)
    code = ast.unparse(fn)
    assert "Employee" not in code
    assert "db" not in inspect.signature(D.get_platform_staff).parameters


def test_it_403s_rather_than_401s():
    """The caller is authenticated; they simply are not platform staff."""
    src = inspect.getsource(D.get_platform_staff)
    assert "HTTP_403_FORBIDDEN" in src


# ── D5: company roles stay out of platform gates ─────────────────────────────

def test_no_platform_endpoint_is_gated_by_a_company_role():
    """`admin` is resolved through the Employee table by RoleChecker and is
    tenant-scoped by construction. Mixing it into a platform gate would put a
    company admin one group membership from cross-tenant reads."""
    for rel in ROUTERS:
        path = os.path.abspath(os.path.join(BACKEND, rel))
        tree = ast.parse(open(path).read())
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sig = ast.unparse(n.args)
            if "get_platform_staff" in sig:
                assert "RoleChecker" not in sig, (
                    f"{n.name} mixes a company role into a platform gate"
                )
