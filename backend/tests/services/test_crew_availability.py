"""ADR-197 Phase 0b — crew availability derivation.

Pure-logic tests of classify_member / derive_availability: the 65% completion
threshold, membership gating, and the 'walker count is a ceiling' route-taker
count that F5 route-creation reads.
"""
import uuid

from app.services.crew_availability import (
    MemberProgress,
    classify_member,
    derive_availability,
    DEFAULT_COMPLETION_THRESHOLD,
)


def _m(role="walker", status="active", has_route=False, pct=None, present=True):
    return MemberProgress(
        employee_id=uuid.uuid4(), name="X", role=role,
        membership_status=status, has_active_route=has_route, route_completion_pct=pct,
        present=present,
    )


class TestClassifyMember:
    def test_active_no_route_is_available(self):
        assert classify_member(_m()).availability == "available"

    def test_departed_is_off_crew(self):
        assert classify_member(_m(status="departed")).availability == "off_crew"

    def test_transferred_is_off_crew(self):
        assert classify_member(_m(status="transferred")).availability == "off_crew"

    def test_route_below_threshold_is_early(self):
        assert classify_member(_m(has_route=True, pct=0.50)).availability == "on_route_early"

    def test_route_at_threshold_is_early(self):
        # exactly 0.65 is NOT past the threshold → still early
        assert classify_member(_m(has_route=True, pct=0.65)).availability == "on_route_early"

    def test_route_above_threshold_is_returning(self):
        assert classify_member(_m(has_route=True, pct=0.80)).availability == "on_route_returning"

    # Presence gate (roll call) — the crew-roster requirement.
    def test_not_yet_marked_present_is_not_arrived(self):
        # present=None → on the crew but roll call not taken → Not Arrived.
        assert classify_member(_m(present=None)).availability == "not_arrived"

    def test_marked_present_becomes_available(self):
        # roll call marked them in → falls through to the normal derivation.
        assert classify_member(_m(present=True)).availability == "available"

    def test_absent_ncns_is_off_crew(self):
        assert classify_member(_m(present=False)).availability == "off_crew"

    def test_not_arrived_on_route_still_not_arrived(self):
        # Presence dominates: even with a route, no roll call → Not Arrived.
        assert classify_member(_m(present=None, has_route=True, pct=0.9)).availability == "not_arrived"


class TestPresenceExcludedFromAvailableCount:
    def test_not_arrived_not_counted_available(self):
        members = [
            _m(present=None),   # not arrived → NOT available
            _m(present=None),   # not arrived → NOT available
            _m(present=True),   # available
        ]
        _entries, active_crew, available = derive_availability(members)
        assert available == 1          # only the marked-present member
        assert active_crew == 3        # membership still active for all three

    def test_marking_present_increments_available(self):
        before = derive_availability([_m(present=None)])[2]
        after = derive_availability([_m(present=True)])[2]
        assert before == 0 and after == 1


class TestDeriveAvailability:
    def test_the_users_scenario(self):
        # ADR-197 example: started 10, 2 transferred, 6 at truck awaiting a route,
        # 1 early (<=65%), 1 near completion (>65%). Expect available_for_route = 7.
        members = (
            [_m(status="transferred") for _ in range(2)]
            + [_m() for _ in range(6)]                       # available
            + [_m(has_route=True, pct=0.40)]                 # early → not available
            + [_m(has_route=True, pct=0.90)]                 # returning → available
        )
        entries, active_crew, available = derive_availability(members)
        assert active_crew == 8              # 10 - 2 transferred
        assert available == 7                # 6 available + 1 returning (early one excluded)

    def test_driver_excluded_from_route_takers(self):
        members = [_m(role="driver"), _m(role="walker")]
        _, active, available = derive_availability(members)
        assert active == 2
        assert available == 1                # driver runs the truck, not a route

    def test_custom_threshold(self):
        # With a 0.5 threshold, a 0.6 route counts as returning (available).
        m = _m(has_route=True, pct=0.60)
        assert classify_member(m, threshold=0.5).availability == "on_route_returning"
        assert classify_member(m, threshold=0.65).availability == "on_route_early"

    def test_default_threshold_value(self):
        assert DEFAULT_COMPLETION_THRESHOLD == 0.65
