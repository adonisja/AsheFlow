"""ADR-286 — a hub assignment does not mean dispatch ran.

THE FAILURE
-----------
Creating a hub writes a TruckAssignment. Two guards read "a TruckAssignment
exists for today" as "dispatch has run":

  1. workflow_status fell to "dispatched", and the frontend gates Run Dispatch
     on `workflowStep !== 'none'` — so the button greyed out on a day dispatch
     had never run.
  2. trigger_dispatch's 409 refused the run for the same reason.

The disabled button HID the second bug: had it been enabled, the run would have
409'd anyway. Reproduced on staging against live data — one assignment,
is_hub=True, zero non-hub rows.

This is ADR-274's defect mirrored. That ADR removed the correlation on the hub
side ("planned means hub"); this removes it on the workflow side.

dispatch.py is proprietary; CI copies it in before pytest, so there is
deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


GET = _code_only(dispatch.get_daily_dispatch)
TRIGGER = _code_only(dispatch.trigger_dispatch)


class TestWorkflowStatusIgnoresHubs:
    def test_it_derives_from_non_hub_assignments(self):
        assert 'if not s["is_hub"]' in GET
        assert "operational_statuses" in GET

    def test_a_hub_only_day_reports_none(self):
        """"none" means dispatch has not run. Previously this said
        "dispatched" — the state meaning it already had."""
        assert "if not operational_statuses:" in GET
        i = GET.index("if not operational_statuses:")
        assert 'workflow_status = "none"' in GET[i : i + 120]

    def test_the_phases_read_the_filtered_set(self):
        """Deriving the phases from all_statuses while only the emptiness check
        used the filtered set would leave a hub able to publish the day."""
        assert '"completed" in operational_statuses' in GET
        assert '"active" in operational_statuses' in GET
        assert "all_statuses" not in GET

    def test_it_reuses_the_hub_ids_already_computed(self):
        """`is_hub` per truck is built above for the response (ADR-274 D1);
        a second query would be a second thing to keep in sync."""
        assert GET.index('"is_hub": str(a.truck_id) in hub_truck_ids') < GET.index("operational_statuses")


class TestTheDoubleDispatchGuardIgnoresHubs:
    def test_it_joins_trucks_and_excludes_hubs(self):
        """Anchored to the GUARD's query, not the whole function.

        `Truck.is_hub == False` appears twice in trigger_dispatch — the other
        is truck-id validation (ADR-274). Asserting on the function as a whole
        matched that one, so deleting the guard's filter passed this test:
        planted and confirmed escaped before it was narrowed."""
        i = TRIGGER.index("existing = (")
        guard = TRIGGER[i : TRIGGER.index(".first()", i)]
        assert "Truck.is_hub == False" in guard, (
            "the double-dispatch guard no longer excludes hubs"
        )

    def test_the_join_is_company_scoped_on_both_sides(self):
        """ADR-115 dim 1 — a join widens the query, so the joined table needs
        its own tenant filter."""
        i = TRIGGER.index("existing = (")
        window = TRIGGER[i : i + 500]
        assert "TruckAssignment.company_id == caller.company_id" in window
        assert "Truck.company_id == caller.company_id" in window

    def test_it_still_refuses_a_real_second_run(self):
        """The guard's purpose survives: a non-hub assignment still 409s."""
        assert "HTTP_409_CONFLICT" in TRIGGER
        assert "Dispatch already exists" in TRIGGER


class TestBothHalvesAreRequired:
    def test_the_ui_gate_and_the_backend_guard_agree(self):
        """Fixing only the status re-enables a button whose action 409s; fixing
        only the guard leaves the button disabled so nobody reaches the fix."""
        assert 'workflow_status = "none"' in GET
        assert "Truck.is_hub == False" in TRIGGER

    def test_the_frontend_handles_the_new_value(self):
        """THE correction to this ADR's first draft: it claimed the frontend
        already handled "none". It did not — the value fell through the ternary
        to the `: 'dispatched'` default, which is the bug arriving by a new
        route."""
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[3]
            / "frontend" / "src" / "pages" / "DispatchDashboard.tsx"
        )
        if not page.exists():
            return
        text = page.read_text()
        assert "dispatchData.workflow_status === 'none'" in text, (
            "an explicit 'none' falls through to 'dispatched' without this branch"
        )

    def test_the_typescript_union_includes_none(self):
        from pathlib import Path

        types = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "types.ts"
        if not types.exists():
            return
        text = types.read_text()
        i = text.index("workflow_status?:")
        assert "'none'" in text[i : i + 90]


class TestEveryConsumerHandlesNone:
    """ADR-115 dim 8. "none" is a NEW value, and it is TRUTHY — every consumer
    that tested `!!workflow_status` read it as "dispatch ran", which is the
    opposite of what it means.

    Found by the audit, not by a failing test: the button worked because the
    'none' branch fires first, but the surrounding invariant was false and the
    next reader would have inherited it.
    """

    @staticmethod
    def _page(*parts):
        from pathlib import Path

        return Path(__file__).resolve().parents[3].joinpath(*parts)

    def test_dashboard_has_status_excludes_none(self):
        p = self._page("frontend", "src", "pages", "DispatchDashboard.tsx")
        if not p.exists():
            return
        text = p.read_text()
        # Both call sites; a bare `!!workflow_status` reads "none" as truthy.
        assert text.count("workflow_status !== 'none'") == 2, (
            "a hub-only day would be treated as 'dispatch ran'"
        )

    def test_dispatch_home_type_and_default(self):
        p = self._page("frontend", "src", "pages", "DispatchHome.tsx")
        if not p.exists():
            return
        text = p.read_text()
        i = text.index("workflow_status?:")
        assert "'none'" in text[i : i + 90], "local type omits the new value"
        assert "workflow_status ?? 'none'" in text, (
            "defaulting to 'dispatched' claims dispatch ran when data is absent"
        )

    def test_mobile_falls_through_to_planned(self):
        """Mobile maps anything that is not finalized/published to 'planned',
        so "none" is already correct there — asserted so a future refactor to
        an explicit map does not drop it."""
        p = self._page("mobile", "src", "screens", "Notifications", "NotificationsScreen.tsx")
        if not p.exists():
            return
        text = p.read_text()
        i = text.index("workflow_status ??")
        window = text[i : i + 320]
        assert "setDispatchPhase('planned')" in window
