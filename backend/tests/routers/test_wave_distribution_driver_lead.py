"""A driver can lead wave distribution on their own truck (ADR-274 D18).

WHY THIS EXISTS
---------------
ADR-274 D10 established that a hub has no captain, so the DRIVER is its route
lead. The authority was verified at the time by reading the gate —
`ROUTE_LEAD_ROLES` already contains `driver` — and no code changed.

But nothing exercised it. `tests/services/test_wave_distribution.py` has 26
tests against the SERVICE (pool building, matching, urgency); none goes through
the endpoint, and none uses a driver caller. Every test and code comment around
the route-lead endpoints talks about captains and trainers.

So the driver path was correct-by-inspection and unrun — which is exactly the
state that lets a later refactor quietly break it. These tests pin the two
properties that matter operationally:

  1. a driver CAN distribute waves on the truck they crew
  2. a driver CANNOT on a truck they do not crew (same company)

Property 2 is the one worth having. `company_id` scoping does not stop it — two
trucks in the same tenant — so the only thing standing between a driver and
another crew's route assignments is `_assert_truck_scope`.

SOURCE-READING, DELIBERATELY
----------------------------
The endpoint needs a live session, Redis, a committed sort and a roll call.
The property under test is which CHECK runs and where, which is visible in the
source. The behavioural half is covered by the service tests next door.
"""
import re
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
ROUTER = BACKEND / "app" / "routers" / "walker_routes.py"
CONSTANTS = BACKEND / "app" / "services" / "constants.py"


def _endpoint(name: str) -> str:
    """One endpoint's body, comments and docstring stripped.

    Both are stripped because this file explains truck scoping at length in
    prose — an assertion that matched a comment would pass against an endpoint
    that had lost the check entirely.
    """
    text = ROUTER.read_text(encoding="utf-8")
    start = text.index(f"def {name}(")
    nxt = text.find("\n@router.", start)
    body = text[start:nxt if nxt != -1 else len(text)]
    if '"""' in body:
        a = body.index('"""')
        b = body.index('"""', a + 3) + 3
        body = body[:a] + body[b:]
    return "\n".join(
        l.strip() for l in body.splitlines()
        if l.strip() and not l.strip().startswith("#")
    )


class TestStrippingWorks:
    def test_comments_and_docstring_are_gone(self):
        src = _endpoint("wave_distribution")
        assert "_assert_truck_scope" in src, "endpoint body not captured"
        assert "Object-level ownership" not in src, (
            "comments survived stripping — an assertion could match prose "
            "instead of the check itself"
        )


class TestDriverIsARouteLead:
    def test_driver_is_in_the_gate(self):
        # ADR-274 D10: a hub has no captain, so the driver leads. If this is
        # ever removed, a hub crew cannot assign their own routes at all.
        src = CONSTANTS.read_text(encoding="utf-8")
        block = src[src.index("ROUTE_LEAD_ROLES"):src.index("TRUCK_SCOPED_ROLES")]
        assert '"driver"' in block, (
            "driver dropped from ROUTE_LEAD_ROLES — a hub, which has no "
            "captain by design, would have no one able to lead its routes"
        )

    def test_driver_is_truck_scoped(self):
        # Being a route lead is not enough: the driver's reach must still be
        # limited to their own truck. Both halves are required.
        src = CONSTANTS.read_text(encoding="utf-8")
        block = src[src.index("TRUCK_SCOPED_ROLES"):]
        assert '"driver"' in block, (
            "driver is a route lead but no longer truck-scoped — it could act "
            "on any truck in the company"
        )


class TestOwnershipIsEnforced:
    """The check that stops a driver acting on another crew's truck."""

    @pytest.mark.parametrize("endpoint", [
        "wave_distribution",
        "commit_sort",
        "reassign_route",
        "unassign_route",
        "split_pair",
    ])
    def test_route_lead_write_asserts_truck_scope(self, endpoint: str):
        src = _endpoint(endpoint)
        assert "_assert_truck_scope" in src, (
            f"{endpoint} has no object-level ownership check, so a driver on "
            "truck A could act on truck B — same company, so company_id "
            "scoping does not stop it (ADR-115 D2)"
        )

    def test_wave_distribution_scopes_the_id_the_CLIENT_sent(self):
        # The subtle half: truck_assignment_id comes from the request body, so
        # the check must be against THAT id, not against something re-derived
        # server-side (which would be checking the wrong object).
        src = _endpoint("wave_distribution")
        assert "_assert_truck_scope(caller, body.truck_assignment_id, db)" in src, (
            "the ownership check does not cover the client-supplied "
            "truck_assignment_id"
        )

    def test_the_check_runs_before_any_mutation(self):
        src = _endpoint("wave_distribution")
        guard = src.index("_assert_truck_scope")
        for mutation in ("db.add(", "db.commit()", "db.flush()"):
            if mutation in src:
                assert guard < src.index(mutation), (
                    f"{mutation} happens before the ownership check — a "
                    "forbidden caller would still have written"
                )


class TestScopeHelperContract:
    """`_assert_truck_scope` is the whole protection; pin what it does."""

    def _helper(self) -> str:
        text = ROUTER.read_text(encoding="utf-8")
        start = text.index("def _assert_truck_scope(")
        return text[start:text.index("\ndef ", start + 10)]

    def test_membership_is_the_test(self):
        src = self._helper()
        assert "AssignmentMember.assignment_id == truck_assignment_id" in src
        assert "AssignmentMember.employee_id == caller.id" in src, (
            "the helper does not check that the CALLER is on the truck"
        )

    def test_membership_lookup_is_company_scoped(self):
        assert "AssignmentMember.company_id == caller.company_id" in self._helper()

    def test_oversight_roles_pass_through(self):
        # Dispatch must be able to fix any truck; scoping them would break the
        # station-side workflow this endpoint also serves.
        assert "if caller.role in _DISPATCH_ROLES:" in self._helper()

    def test_it_403s_rather_than_404s(self):
        # 404 would leak whether that truck assignment exists.
        assert "HTTP_403_FORBIDDEN" in self._helper()


class TestHubHasNoCaptainAssumption:
    def test_trainer_pairing_is_optional(self):
        # A hub crew has no trainees, so a driver-led distribution never
        # supplies trainer_id. It must not be required unconditionally.
        src = _endpoint("wave_distribution")
        assert "if body.trainee_id and not body.trainer_id:" in src, (
            "trainer_id is required regardless of whether a trainee is being "
            "assigned — a hub driver, who has neither, could not distribute"
        )


class TestUiDoesNotEscalateToANonexistentCaptain:
    """Copy shown to whoever leads the sort — on a hub, that is the driver."""

    def _screen(self) -> str:
        return (BACKEND.parent / "mobile" / "src" / "screens" / "Trainer"
                / "RouteSortScreen.tsx").read_text(encoding="utf-8")

    def test_misroute_copy_branches_on_hub(self):
        # "flag for captain to reassign" names a role a hub does not have, and
        # the person reading it IS the route lead — so it tells them to escalate
        # to themselves via someone who does not exist.
        src = self._screen()
        i = src.index("No covering route")
        block = src[max(0, i - 400):i + 240]
        assert "isHub" in block, (
            "the misroute message is unconditional — a hub driver is told to "
            "flag it for a captain their truck does not have"
        )

    def test_the_non_hub_copy_is_unchanged(self):
        # A regular truck still escalates to its captain; this must not have
        # become 'do it yourself' for everyone.
        assert "flag for captain to reassign" in self._screen()
