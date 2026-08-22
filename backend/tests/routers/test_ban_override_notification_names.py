"""The ban-override notification must name people, not print UUIDs.

WHY THIS TEST EXISTS
--------------------
This fix was made on AsheFlow-private `main` in June (0184293) and never
reached `staging`, so the bug it fixed was still live in August. It surfaced
only because CI on `master` pulls the private `main` branch, which had frozen
at 2026-06-06 — the stale branch was simultaneously hiding a real fix and
breaking the build with stale imports.

dispatch.py is proprietary; CI copies it in from AsheFlow-private before
pytest, so there is deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


class TestBanOverrideNotificationIsReadable:
    def test_the_message_interpolates_names_not_ids(self):
        """A dispatcher reading 'walker 7f3a-… evicted from truck 91b2-…' cannot
        act on it. The whole point of the notification is that it is legible."""
        src = _code_only(dispatch.trigger_dispatch)
        assert "walker {evicted_name} evicted from truck " in src
        assert "{truck_name} in favour of {favoured_name}." in src

    def test_raw_ids_are_not_interpolated(self):
        src = _code_only(dispatch.trigger_dispatch)
        assert "walker {evicted_id} evicted" not in src
        assert "in favour of {favoured_id}" not in src

    def test_the_lookups_are_company_scoped(self):
        """ADR-115 dim 1. Three secondary lookups, each a cross-tenant read if
        unscoped — exactly the 'inner query' case the checklist calls out."""
        src = _code_only(dispatch.trigger_dispatch)
        for needle in (
            "Employee.id == evicted_id,  Employee.company_id == caller.company_id",
            "Employee.id == favoured_id, Employee.company_id == caller.company_id",
            "Truck.id == from_truck,        Truck.company_id == caller.company_id",
        ):
            assert needle in src, f"missing company-scoped lookup: {needle}"

    def test_a_missing_row_falls_back_to_the_id(self):
        """A deleted employee must not blank the message or raise — the id is
        worse than a name but far better than nothing."""
        src = _code_only(dispatch.trigger_dispatch)
        assert "if evicted_emp  else str(evicted_id)" in src
        assert "if favoured_emp else str(favoured_id)" in src
        assert "if truck_obj    else str(from_truck)" in src
