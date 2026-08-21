"""ADR-256 — the authority sets, and the two ways they can be wrong.

These pin membership rather than endpoint behaviour, because the failure mode being
guarded is a *list edit*: someone adds a role to the wrong tuple and no test notices.
The full suite stayed green through the entire gate rewrite, which is exactly the
problem — nothing existing exercises a captain.

Two distinct failures are covered:

  1. a role MISSING from a set it needs (captain locked out of its own job)
  2. a role PRESENT in a set it must not be in (trainer keeping route-lead authority
     after ADR-256 D5 removed it, or captain landing in the unscoped-oversight set
     and gaining cross-truck reach)

(2) is the dangerous direction and the one a "does the captain work?" test misses.
"""
import pytest

from app.services.constants import (
    ROUTE_LEAD_ROLES,
    TRUCK_SCOPED_ROLES,
    STATION_RESOLVE_ROLES,
    OVERSIGHT_ROLES,
)


class TestRouteLeadRoles:
    def test_captain_leads_routes(self):
        assert "captain" in ROUTE_LEAD_ROLES

    def test_driver_still_leads_routes(self):
        """D5: the captain organises routes WITH the driver — driver is not displaced."""
        assert "driver" in ROUTE_LEAD_ROLES

    def test_trainer_no_longer_leads_routes(self):
        """ADR-256 D5. A trainer raises route needs to the captain; the captain decides.

        This is the assertion that fails if someone 'restores' trainer to fix a
        permissions complaint without reading the hierarchy change.
        """
        assert "trainer" not in ROUTE_LEAD_ROLES

    def test_walker_and_trainee_never_lead_routes(self):
        assert "walker" not in ROUTE_LEAD_ROLES
        assert "trainee" not in ROUTE_LEAD_ROLES


class TestTruckScopedRoles:
    """The set whose reads are narrowed to their OWN truck."""

    def test_captain_is_truck_scoped(self):
        assert "captain" in TRUCK_SCOPED_ROLES

    def test_driver_is_truck_scoped(self):
        assert "driver" in TRUCK_SCOPED_ROLES

    @pytest.mark.parametrize("role", ["dispatch", "management", "admin", "field_supervisor"])
    def test_station_side_roles_are_not_truck_scoped(self, role):
        """These see every truck. Putting one here would NARROW them to one truck —
        a functional break rather than a leak, but a break all the same."""
        assert role not in TRUCK_SCOPED_ROLES

    def test_trainer_is_not_truck_scoped(self):
        """D5 moved truck-level authority to captain."""
        assert "trainer" not in TRUCK_SCOPED_ROLES


class TestFieldSupervisorBoundary:
    """ADR-256 D12 — road-facing oversight, NOT station-side execution."""

    def test_field_supervisor_has_oversight(self):
        assert "field_supervisor" in OVERSIGHT_ROLES

    def test_field_supervisor_may_lead_routes(self):
        assert "field_supervisor" in ROUTE_LEAD_ROLES

    def test_field_supervisor_cannot_resolve_station_exceptions(self):
        """The D12 line: resolving missing/damaged/handoff discrepancies stays dispatch.

        ADR-016 settled that an oversight role does not thereby acquire dispatch's
        execution authority; ADR-242 is what happens when a gate name erodes it.
        """
        assert "field_supervisor" not in STATION_RESOLVE_ROLES

    def test_station_resolve_is_dispatch_and_up_only(self):
        assert set(STATION_RESOLVE_ROLES) == {"dispatch", "management", "admin"}


class TestCaptainIsNotOversight:
    """A captain leads ONE truck. It must never reach the unscoped-oversight set."""

    def test_captain_is_not_oversight(self):
        assert "captain" not in OVERSIGHT_ROLES

    def test_captain_cannot_resolve_station_exceptions(self):
        assert "captain" not in STATION_RESOLVE_ROLES


def _walker_routes_has_rename() -> bool:
    """Is the ADR-256 gate rename present in THIS build's walker_routes?

    walker_routes.py is gitignored, so it is either ABSENT from the public repo
    (ModuleNotFoundError) or present as a pre-rename copy (no _allow_route_lead).
    Both are handled here, and the import is inside the function on purpose: at
    module level a missing module is a COLLECTION error, which aborts the entire
    pytest run rather than skipping one file.
    """
    try:
        from app.routers import walker_routes
    except (ImportError, ModuleNotFoundError):
        return False
    return hasattr(walker_routes, "_allow_route_lead")


@pytest.mark.skipif(
    not _walker_routes_has_rename(),
    reason=(
        "walker_routes is gitignored: absent from the public repo, or present as a "
        "pre-ADR-256 copy without _allow_route_lead."
    ),
)
class TestGatesUseTheSharedSets:
    """Every renamed gate resolves from the shared tuples, not a re-typed literal.

    The 14 copies of the old list drifted precisely because each was typed by hand.
    """

    def test_all_route_lead_gates_agree(self):
        from app.routers import (
            walker_routes, rts, building_profiles, crew_status, assignment_members,
        )
        gates = {
            "walker_routes": walker_routes._allow_route_lead.allowed_roles,
            "rts": rts._allow_route_lead.allowed_roles,
            "building_profiles": building_profiles._allow_route_lead.allowed_roles,
            "crew_status": crew_status._allow_route_lead.allowed_roles,
            "assignment_members": assignment_members.allow_route_lead.allowed_roles,
        }
        expected = list(ROUTE_LEAD_ROLES)
        for name, roles in gates.items():
            assert roles == expected, f"{name} drifted from ROUTE_LEAD_ROLES"

    def test_old_captain_named_gates_are_gone(self):
        """D13: a gate named for a group invites the ADR-242 misreading."""
        from app.routers import walker_routes, rts, building_profiles, crew_status
        for mod in (walker_routes, rts, building_profiles, crew_status):
            assert not hasattr(mod, "_allow_captain"), f"{mod.__name__} still exports _allow_captain"


class TestCaptainInDispatchRoleLiterals:
    """The bug this file's docstring predicted, in the form it actually took.

    The sets above are all guarded. What was NOT guarded were the hardcoded role
    LISTS scattered through routers and services — literals that no constant
    covers, so no membership test could see them.

    Three of them omitted captain, and the operator hit two on one page:

      * `/schedule/available` built its response dict WITHOUT a "captain" key,
        and its `if role in pool` guard then discarded every captain silently —
        no error, no log. A captain removed from a truck never reappeared in the
        unassigned list, so they looked deleted rather than unassigned, and
        could not be dragged back.
      * `/dispatch/unavailable-staff` defaulted to driver/trainer/walker, so a
        captain on approved PTO was invisible in the call-in list — the one
        person who could staff a captainless truck, missing from the screen
        warning about it.

    Read the source rather than calling the endpoints: the failure is a literal
    in a signature or a dict, and that is exactly what needs pinning.
    """

    def _source(self, relpath: str) -> str:
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]   # backend/
        return (root / relpath).read_text(encoding="utf-8")

    def test_available_pool_response_has_captain_key(self):
        src = self._source("app/routers/schedule.py")
        assert '"captain": []' in src, (
            "/schedule/available must build a captain bucket — without the key, "
            "`if role in pool` drops captains silently"
        )

    def test_unavailable_staff_default_roles_include_captain(self):
        src = self._source("app/routers/dispatch.py")
        line = next(
            (ln for ln in src.splitlines() if "roles: List[str] = Query(default=" in ln),
            None,
        )
        assert line is not None, "unavailable-staff roles default not found"
        assert "captain" in line, (
            "a captain excluded by PTO belongs in the call-in list like any "
            f"other truck role — got: {line.strip()}"
        )

    def test_available_pool_service_default_includes_captain(self):
        src = self._source("app/services/available_pool.py")
        assert 'roles or ["driver", "captain", "trainer", "walker"]' in src, (
            "get_unavailable_staff's fallback default must include captain, so a "
            "direct caller behaves like the endpoint"
        )

    def test_available_pool_service_queries_captains(self):
        # The service was already correct; pin it so the two stay in agreement.
        src = self._source("app/services/available_pool.py")
        assert '"captain"' in src and '"captains"' in src
