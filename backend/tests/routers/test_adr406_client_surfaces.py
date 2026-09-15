"""ADR-406 D2 — a reserved route reaches BOTH clients.

The operator's reason for the feature is that the walker sees it:

    helps stimulate activity in deliberately underperforming walkers and
    maintain a clear signal for performance tracking later

A reserved route the walker cannot see is a note in the captain's head. So
"the endpoint returns it" is not the deliverable — rendering it is, on both
surfaces, since no app is shipped and the browser is the field surface today
(ADR-402 D4).

This is the ADR-381 check made specific: an endpoint with no caller is a feature
that does not exist.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB_WALKER = ROOT / "frontend" / "src" / "pages" / "MyWorkforceRoute.tsx"
WEB_CAPTAIN = ROOT / "frontend" / "src" / "pages" / "WorkforceSort.tsx"
MOBILE_WALKER = (ROOT / "mobile" / "src" / "screens" / "Walker"
                 / "MyWorkforceRouteScreen.tsx")


@pytest.mark.parametrize("path", [WEB_WALKER, WEB_CAPTAIN, MOBILE_WALKER],
                         ids=lambda p: p.name)
def test_the_surface_exists(path: Path) -> None:
    assert path.exists(), f"{path.name} is gone — the feature lost a surface"


class TestTheWalkerIsToldOnBothClients:
    def test_web_renders_reserved_routes(self) -> None:
        src = WEB_WALKER.read_text()
        assert "reserved_routes" in src, (
            "the web walker view no longer reads reserved_routes, so a reserved "
            "route cannot reach the person it is reserved for"
        )

    def test_mobile_renders_reserved_routes(self) -> None:
        src = MOBILE_WALKER.read_text()
        assert "reserved_routes" in src, (
            "the mobile walker screen no longer reads reserved_routes"
        )

    @pytest.mark.parametrize("path", [WEB_WALKER, MOBILE_WALKER],
                             ids=lambda p: p.name)
    def test_a_reserved_route_offers_no_start_action(self, path: Path) -> None:
        """D2. The depart endpoint refuses a route that is not `assigned`, so a
        start button could only ever produce a 409 — and the sequencing is the
        captain's to control.

        Checks for a CALL to the depart endpoint, not for words that look like
        one. A first version searched the whitespace-stripped source for
        "startroute" and matched a COMMENT explaining why no such button exists
        — the same trap as testing for a feature by grepping for its name.
        """
        import re
        src = path.read_text()
        # Strip // and /* */ comments before looking for a call.
        code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        assert "/depart" not in code, (
            f"{path.name} calls the depart endpoint; a walker cannot start a "
            f"route in workforce mode — the captain records the departure "
            f"(ADR-300 D1), and a reserved route is not startable at all "
            f"(ADR-406 D2)"
        )


class TestTheCaptainSeesTheDifference:
    def test_the_route_card_distinguishes_reserved_from_assigned(self) -> None:
        """A route held for someone mid-route answers "what can be walked now"
        differently from one waiting to go. Both read `assigned` before this."""
        src = WEB_CAPTAIN.read_text()
        assert "assignment_kind === 'reserved'" in src, (
            "the captain's route card no longer distinguishes a reserved route "
            "from one that is ready to walk (ADR-406 D1)"
        )


class TestModeGating:
    def test_the_web_walker_page_is_workforce_only(self) -> None:
        """Full mode has its own /my-route built on stops. A tenant gets one or
        the other, never both — the two nav entries sit on opposite feature
        gates."""
        nav = (ROOT / "frontend" / "src" / "config" / "navConfig.ts").read_text()
        assert "'/my-workforce-route'" in nav
        line = next(l for l in nav.splitlines() if "'/my-workforce-route'" in l)
        assert "feature: 'workforce_sort'" in line, (
            "the workforce walker page is not gated on workforce_sort, so a "
            "full-mode walker would see two My Route tabs"
        )
