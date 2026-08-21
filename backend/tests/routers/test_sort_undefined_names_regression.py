"""Regression tests for NameError bugs in sort.py surfaced by static analysis.

Two admin/debug endpoints referenced names that were never in scope, so they
would raise NameError the moment they ran:

  - geoclient_probe used _GEOCLIENT_BASE (defined in tasks.enrich_manifest, never
    imported here).
  - reassign_tbas constructed AuditLog(...) without importing it (sibling
    functions import it locally; this one did not).

Both endpoints have no client caller yet, which is why the bugs never surfaced
in practice. These tests pin the fix (local imports) so it can't regress.

app.routers.sort imports proprietary services absent in public CI — skip the
whole module if so.
"""
import pytest

try:
    import app.routers.sort as sort_mod
except ImportError:
    pytest.skip("proprietary sort deps not available (CI skip)", allow_module_level=True)


def _name_resolvable_in(func, name: str) -> bool:
    """True if `name` is reachable from func's module globals or via one of the
    local `from X import name` statements in its source (the fix pattern used
    throughout sort.py)."""
    import inspect
    if name in func.__globals__:
        return True
    src = inspect.getsource(func)
    return f"import {name}" in src


def test_geoclient_probe_can_resolve_geoclient_base():
    # The constant it depends on must be importable at all.
    from app.tasks.enrich_manifest import _GEOCLIENT_BASE  # noqa: F401
    assert _name_resolvable_in(sort_mod.geoclient_probe, "_GEOCLIENT_BASE")


def test_reassign_tbas_can_resolve_auditlog():
    from app.models.audit_log import AuditLog  # noqa: F401
    assert _name_resolvable_in(sort_mod.reassign_tbas, "AuditLog")
