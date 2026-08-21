"""Web nav and route gates agree, and a captain has a home (ADR-274 D20).

TWO PROPERTIES, ONE FILE — they failed together.

1. THE CAPTAIN HAD NO WEB SURFACE
   `captain` was absent from the `Role` union in navConfig.ts entirely, so it
   appeared in no nav item and no route gate. `homeRouteForGroups` fell through
   to '/', which renders WorkerView — a driver/walker page with none of a route
   lead's signals. A captain could log in and reach nothing they own.

2. NAV AND ROUTE GATES ARE MAINTAINED IN PARALLEL
   navConfig.ts's own docstring says it is "the single source of truth for
   role-based navigation AND route access", and that App.tsx gates "read their
   allowed-role sets from routeRoles(path) — so a nav tab and its route can
   never disagree again".

   In practice ONE route derives its gate that way; the other 41 are hand-written
   literals. They happen to agree (verified: zero drift), but nothing enforces
   it, so adding a role means editing two lists and hoping.

   This test is the enforcement the docstring already claims. It does not force
   a refactor of 41 gates — it locks in a property that currently holds.

WHY A PYTHON TEST FOR TYPESCRIPT FILES
The web has no test runner wired into CI; the backend suite is what runs on
every push. Parsing two files for role literals needs no DOM and no bundler, so
it belongs where it will actually execute.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "frontend" / "src" / "App.tsx"
NAV = ROOT / "frontend" / "src" / "config" / "navConfig.ts"

# Mirrors ALL_FIELD in navConfig.ts. If that constant changes, this must too —
# `test_all_field_matches_this_constant` fails if they drift.
_ALL_FIELD = {"driver", "walker", "trainer", "trainee", "captain"}


def _nav_roles() -> dict[str, set[str]]:
    """path -> allowed roles, from NAV_ITEMS."""
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"\{ path: '([^']*)',[^}]*roles: \[([^\]]*)\]", NAV.read_text(encoding="utf-8")):
        roles: set[str] = set()
        for raw in m.group(2).split(","):
            raw = raw.strip()
            if "ALL_FIELD" in raw:
                roles |= _ALL_FIELD
            elif raw:
                roles.add(raw.strip("'"))
        out[m.group(1)] = roles
    return out


def _route_roles() -> dict[str, set[str]]:
    """path -> allowed roles, for routes with a LITERAL allowedRoles array.

    Routes using `routeRoles(path)` are in sync by construction and excluded.
    The negative lookahead stops a match running past its own <Route> into the
    next one's allowedRoles — without it, /sort-metrics (which uses routeRoles)
    picked up a neighbouring literal and reported a drift that did not exist.
    """
    out: dict[str, set[str]] = {}
    pattern = r'path="([^"]*)"(?:(?!path=").)*?allowedRoles=\{\[([^\]]*)\]'
    for m in re.finditer(pattern, APP.read_text(encoding="utf-8"), re.S):
        out[m.group(1)] = {r.strip().strip("'") for r in m.group(2).split(",") if r.strip()}
    return out


class TestDetectorIsSound:
    """Guards the guard — a broken parser makes every test below vacuous."""

    def test_both_files_yield_paths(self):
        assert len(_nav_roles()) > 15, "nav parse found almost nothing"
        assert len(_route_roles()) > 15, "route parse found almost nothing"

    def test_all_field_matches_this_constant(self):
        src = NAV.read_text(encoding="utf-8")
        m = re.search(r"const ALL_FIELD: Role\[\] = \[([^\]]*)\]", src)
        assert m, "ALL_FIELD no longer exists — the expansion above is wrong"
        actual = {r.strip().strip("'") for r in m.group(1).split(",") if r.strip()}
        assert actual == _ALL_FIELD, (
            f"ALL_FIELD changed to {sorted(actual)} — update _ALL_FIELD here or "
            "every ALL_FIELD path silently compares against the wrong set"
        )


class TestNoDrift:
    def test_nav_and_route_gates_agree(self):
        nav, routes = _nav_roles(), _route_roles()
        drift = []
        for path, route_set in routes.items():
            if path not in nav:
                continue      # route with no nav tab (a landing page) — fine
            if route_set != nav[path]:
                drift.append(
                    f"{path}: nav-only={sorted(nav[path] - route_set)} "
                    f"route-only={sorted(route_set - nav[path])}"
                )
        assert not drift, (
            "route gates disagree with navConfig — a role can see a tab it "
            "cannot open, or open a page it cannot see:\n  " + "\n  ".join(drift)
        )


class TestCaptainHasAWebHome:
    def test_captain_is_in_the_role_union(self):
        src = NAV.read_text(encoding="utf-8")
        union = src[src.index("export type Role ="):src.index(";", src.index("export type Role ="))]
        assert "'captain'" in union, (
            "captain is not a web Role, so it cannot appear in any nav item or "
            "route gate — a captain logging in reaches nothing they own"
        )

    def test_captain_lands_on_their_dashboard(self):
        src = NAV.read_text(encoding="utf-8")
        block = src[src.index("export function homeRouteForGroups"):]
        block = block[:block.index("}", block.index("return"))]
        assert "'captain'" in block and "/captain-dashboard" in block, (
            "captain falls through to '/', which renders WorkerView — a "
            "driver/walker page with none of a route lead's signals"
        )

    def test_the_dashboard_route_exists_and_is_gated(self):
        src = APP.read_text(encoding="utf-8")
        assert 'path="/captain-dashboard"' in src, "no route for the dashboard"
        i = src.index('path="/captain-dashboard"')
        m = re.search(r"allowedRoles=\{\[([^\]]*)\]", src[i:i + 300])
        assert m, "the captain dashboard route has no role gate"
        roles = {r.strip().strip("'") for r in m.group(1).split(",")}
        assert "captain" in roles, "captains cannot open their own dashboard"

    @pytest.mark.parametrize("path,why", [
        ("/crew-status",   "their truck's crew, which the backend already truck-scopes for captains"),
        ("/walker-sort",   "ADR-256 D5: route assignment is the captain's"),
        ("/anchor-points", "the captain leads the anchor point"),
    ])
    def test_captain_reaches_the_pages_they_lead(self, path: str, why: str):
        nav = _nav_roles()
        assert path in nav, f"{path} is no longer a nav item"
        assert "captain" in nav[path], f"captain cannot reach {path} — {why}"


class TestDashboardShape:
    """The page is a synopsis with drill-through, not a sixth copy of the data."""

    def _page(self) -> str:
        return (ROOT / "frontend" / "src" / "pages" / "CaptainDashboard.tsx").read_text(encoding="utf-8")

    def test_every_card_links_to_the_page_that_owns_the_detail(self):
        # ManagementView's cards are dead ends. A summary with no way through
        # is a worse version of the page it summarises.
        src = self._page()
        for target in ("/crew-status", "/walker-sort", "/field-ops"):
            assert f"to=\"{target}\"" in src, f"no drill-through to {target}"

    def test_empty_state_does_not_fall_back_to_a_previous_day(self):
        # Showing yesterday's crew as if it were today is how someone ends up
        # at the wrong bay talking to the wrong people.
        src = self._page()
        assert "No truck assigned today" in src, "no empty state for an uncrewed captain"
        assert "if (!mine) return;" in src, (
            "the loader continues past a missing assignment — it must stop "
            "rather than resolve a truck from another day"
        )

    def test_card_failures_are_isolated(self):
        # One dead endpoint must not blank the page: the other signals are
        # still actionable.
        src = self._page()
        assert src.count(".catch(() => {})") >= 4, (
            "per-card failures are not tolerated, so one 500 empties the "
            "whole dashboard"
        )
