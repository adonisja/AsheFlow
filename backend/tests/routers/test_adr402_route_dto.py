"""ADR-402 D2/D3 — what the mid-day view needs, and what it must never show.

Source-text tests over `workforce_routes.py`. The DTO is assembled at six call
sites and a partially-converted change fails only on the path nobody tested, so
these assert the wiring at every site rather than trusting one.
"""
from pathlib import Path

import pytest

ROUTER = Path(__file__).resolve().parents[2] / "app" / "routers" / "workforce_routes.py"


def _dto_body(src: str) -> str:
    """Just the WorkforceRouteOut class body.

    Found by scanning to the next top-level `class`, not by naming the neighbour:
    hardcoding the following class makes the test fail when an unrelated model is
    inserted between them, which is a false alarm rather than a finding.
    """
    start = src.index("class WorkforceRouteOut")
    rest = src[start + len("class WorkforceRouteOut"):]
    nxt = rest.find("\nclass ")
    return rest[:nxt] if nxt != -1 else rest


@pytest.fixture(scope="module")
def src() -> str:
    text = ROUTER.read_text()
    # Vacuity guard: every assertion below is trivially true against a file that
    # no longer builds this DTO at all.
    assert "class WorkforceRouteOut" in text, "the DTO under test is gone"
    return text


class TestTimestampsReachTheClient:
    def test_dto_declares_both_stamps(self, src: str) -> None:
        # Assert against the DTO body, not the whole file: `departed_at` also
        # appears on Route queries and in ADR-302 comments, so a file-wide
        # substring check passes even when the FIELD is gone.
        dto = _dto_body(src)
        assert "departed_at: Optional[datetime]" in dto
        assert "returned_at: Optional[datetime]" in dto, (
            "WorkforceRouteOut no longer returns the route timestamps, so the "
            "mid-day view cannot show when a route left or came back, and "
            "duration cannot be derived (ADR-402 D2)"
        )

    def test_no_stored_duration(self, src: str) -> None:
        """Duration is derived from the two stamps, never stored.

        A stored duration is a second source for a fact the timestamps already
        fix — the ADR-401 D3a trap, one ADR earlier.
        """
        assert "duration_minutes" not in src and "duration_seconds" not in src, (
            "a duration field appeared on the route DTO; derive it from "
            "departed_at/returned_at instead (ADR-402 D2)"
        )


class TestParticipantsNotJustExecutor:
    def test_dto_carries_participants(self, src: str) -> None:
        assert "participants: list[RouteParticipantOut]" in src, (
            "the DTO dropped `participants`, so a training pair renders as one "
            "name and the supervising trainer is invisible (ADR-402 D2)"
        )

    def test_every_construction_site_sets_participants(self, src: str) -> None:
        """Six sites build this DTO. All must populate the new field."""
        builds = src.count("WorkforceRouteOut(")  # includes the class definition
        sets = src.count("participants=parts.get(")
        assert sets == builds - 1, (
            f"{builds - 1} WorkforceRouteOut construction sites but only {sets} "
            f"set participants — a site that omits it returns an empty crew on "
            f"one code path only (ADR-402 D2)"
        )

    def test_helper_scopes_both_tables(self, src: str) -> None:
        """Dim 1. An unscoped join surfaces another tenant's employee name."""
        body = src[src.index("def _participants("):src.index("def _participant_names")]
        assert "RouteParticipant.company_id == company_id" in body, (
            "_participants no longer filters RouteParticipant by company_id"
        )
        assert "Employee.company_id == company_id" in body, (
            "_participants joins Employee without a company_id predicate — a "
            "cross-tenant name leak on a fleet-scoped view (ADR-115 dim 1)"
        )


class TestWaveNumberIsNotSurfaced:
    def test_dto_omits_wave_number(self, src: str) -> None:
        """ADR-402 D3.

        `wave_number` increments to max()+1 ACROSS THE TRUCK when a route is
        re-issued, so a walker's first re-issue can read as wave 3. It describes
        neither a truck cycle nor a person's run count; `trip_count` is the
        honest measure. The column is still written — it must simply never reach
        a screen.
        """
        dto = _dto_body(src).replace("`wave_number`", "")
        assert "wave_number" not in dto, (
            "wave_number is back on the route DTO — it is a truck-wide re-issue "
            "counter wearing a name that implies a synchronised wave (ADR-402 D3)"
        )
