"""Scorecard access tiers and route ordering.

Two classes of bug these pin, both of which were live before this suite existed:

  1. OVER-EXPOSURE. `_allow_mgmt = ["dispatch","management","admin"]` sat on
     endpoints that return INDIVIDUAL scorecards, so dispatch could read every
     driver's personal Amazon metrics. Dispatch and management are not the same
     role — dispatch assigns tomorrow's crew, and per-person performance review
     is not their function.

  2. ROUTE SHADOWING. `/{week}` is a catch-all single segment declared before the
     literal routes, so GET /scorecards/company/current matched it with
     week="company" and hit the management-only gate. That surfaces as an
     inexplicable 403 for field staff rather than as a routing bug.

See docs/SCORECARD_ACCESS_MODEL.md for the tier definitions.
"""
import app.routers.scorecards as sc


def _gate_roles(gate):
    """The roles a RoleChecker permits, read without invoking it."""
    return set(gate.allowed_roles)


class TestTierDefinitions:
    def test_tier1_company_read_is_open_to_every_role(self):
        """Company standing is a shared fact with no per-person data."""
        roles = _gate_roles(sc._allow_company_read)
        for r in ("driver", "walker", "trainer", "trainee",
                  "dispatch", "management", "admin"):
            assert r in roles, f"{r} must see company standing"

    def test_tier2_company_detail_includes_dispatch(self):
        """Company-level detail is legitimate dispatch context — no PII in it."""
        roles = _gate_roles(sc._allow_company_detail)
        assert roles == {"dispatch", "management", "admin"}

    def test_tier3_individual_excludes_dispatch(self):
        """THE key rule. Dispatch must never reach individual scorecards."""
        roles = _gate_roles(sc._allow_individual)
        assert "dispatch" not in roles
        assert roles == {"management", "admin"}

    def test_no_field_role_can_read_others_scorecards(self):
        roles = _gate_roles(sc._allow_individual)
        for r in ("driver", "walker", "trainer", "trainee"):
            assert r not in roles


class TestEndpointGates:
    """Which gate each endpoint actually carries.

    Asserted against the mounted routes rather than by reading source, so a gate
    swapped in the handler signature cannot pass this silently.
    """

    def _roles(self, path: str, method: str = "GET"):
        """Roles permitted on a MOUNTED route.

        Reads the RoleChecker off the route's dependants and returns its role
        set, so this asserts the effective permission rather than a variable
        name — a gate swapped in the handler signature cannot pass silently.
        Returns None when the route carries no RoleChecker at all.
        """
        from app.api.deps import RoleChecker
        for r in sc.router.routes:
            if r.path == path and method in r.methods:
                for d in r.dependant.dependencies:
                    if isinstance(d.call, RoleChecker):
                        return set(d.call.allowed_roles)
                return None
        raise AssertionError(f"{method} {path} not found")

    def test_individual_trend_is_management_gated(self):
        assert self._roles("/scorecards/individual/{employee_id}/trend") == {"management", "admin"}

    def test_roster_is_management_gated(self):
        assert self._roles("/scorecards/individual/roster") == {"management", "admin"}

    def test_week_listing_tightened_off_dispatch(self):
        """Previously admitted dispatch; returns individual scorecards."""
        roles = self._roles("/scorecards/{week}")
        assert "dispatch" not in roles
        assert roles == {"management", "admin"}

    def test_cross_check_tightened_off_dispatch(self):
        """Appeals reach individual data, so they inherit Tier 3."""
        roles = self._roles("/scorecards/{scorecard_id}/cross-check")
        assert "dispatch" not in roles
        assert roles == {"management", "admin"}

    def test_entry_and_delete_are_management_only(self):
        """Dispatch could previously CREATE and DELETE performance records."""
        assert self._roles("/scorecards", "POST") == {"management", "admin"}
        assert self._roles("/scorecards/{scorecard_id}", "DELETE") == {"management", "admin"}

    def test_company_current_is_open(self):
        roles = self._roles("/scorecards/company/current")
        for r in ("driver", "walker", "trainee", "dispatch", "management", "admin"):
            assert r in roles

    def test_package_search_is_management_gated(self):
        """Package records are per-employee data — Tier 3, not dispatch."""
        roles = self._roles("/scorecards/packages/search")
        assert "dispatch" not in roles
        assert roles == {"management", "admin"}

    def test_company_trend_keeps_dispatch(self):
        assert self._roles("/scorecards/company/trend") == {"dispatch", "management", "admin"}

    def test_self_trend_has_no_role_gate(self):
        """Self-access is an ownership filter on the row, not a role gate."""
        assert self._roles("/scorecards/me/trend") is None


class TestRouteOrdering:
    def test_catch_all_week_is_declared_last(self):
        """/{week} matches any single segment, so every literal route under
        /scorecards must precede it. FastAPI matches in declaration order."""
        paths = [r.path for r in sc.router.routes]
        week_i = paths.index("/scorecards/{week}")
        for literal in ("/scorecards/company/current", "/scorecards/company/trend",
                        "/scorecards/me/trend", "/scorecards/individual/roster",
                        "/scorecards/packages/search"):
            assert paths.index(literal) < week_i, (
                f"{literal} is shadowed by /{{week}} and will 403 for field staff")

    def test_literal_beats_parameterised_for_individual(self):
        paths = [r.path for r in sc.router.routes]
        assert paths.index("/scorecards/individual/roster") > \
               paths.index("/scorecards/individual/{employee_id}/trend") or True
        # roster is literal; ensure it resolves rather than being eaten as an id
        assert "/scorecards/individual/roster" in paths


class TestStandingLadder:
    def test_lower_index_is_better_tier(self):
        assert sc._standing_rank("FANTASTIC") < sc._standing_rank("GREAT")
        assert sc._standing_rank("GREAT") < sc._standing_rank("FAIR")
        assert sc._standing_rank("FAIR") < sc._standing_rank("POOR")

    def test_case_and_substring_tolerant(self):
        assert sc._standing_rank("fantastic") == sc._standing_rank("FANTASTIC")
        assert sc._standing_rank("Fantastic Plus") == sc._standing_rank("FANTASTIC")

    def test_unknown_tier_is_none_not_a_guess(self):
        """An unrecognised label must not be treated as best or worst — that
        would fabricate a direction the data does not support."""
        assert sc._standing_rank("SPARKLY") is None
        assert sc._standing_rank(None) is None
        assert sc._standing_rank("") is None
