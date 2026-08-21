"""Operational TBA lookup (ADR-245).

Dispatch needs "who has this package?" from a TBA alone. Every other package
read is route-scoped, so finding one meant already knowing its route.

The subtle risk here is the suffix match. Postgres has no direct "any array
element ends with X", so the SQL filters on
array_to_string(tba_numbers, ',') ILIKE '%needle%' — which can match ACROSS an
element boundary. Each element is therefore re-checked in Python.
"""
import inspect

from app.api.deps import RoleChecker
import app.routers.package_lookup as pl


class TestAccess:
    def test_gate_includes_dispatch(self):
        """Operational tracking, not performance data — dispatch is in scope
        here even though ADR-242 excludes it from appeal evidence."""
        assert set(pl._allow_ops.allowed_roles) == {"dispatch", "management", "admin"}

    def test_no_field_role_can_look_up_arbitrary_packages(self):
        for r in ("driver", "walker", "trainer", "trainee"):
            assert r not in pl._allow_ops.allowed_roles

    def test_route_carries_the_gate(self):
        for route in pl.router.routes:
            gates = [d.call for d in route.dependant.dependencies
                     if isinstance(d.call, RoleChecker)]
            assert gates, f"{route.path} is ungated"
            assert set(gates[0].allowed_roles) == {"dispatch", "management", "admin"}

    def test_appeal_search_stays_tier_3(self):
        """This endpoint must not widen the Tier 3 gate it sits beside."""
        import app.routers.scorecards as sc
        assert set(sc._allow_individual.allowed_roles) == {"management", "admin"}


class TestSuffixMatching:
    """_matches is what keeps the SQL's array_to_string trick honest."""

    def test_suffix_matches_element_end(self):
        assert pl._matches("TBA303912345447", "447", exact=False)

    def test_suffix_is_case_insensitive(self):
        assert pl._matches("tba30391234544a", "44A", exact=False)

    def test_suffix_does_not_match_mid_string(self):
        """'447' inside a TBA is not a suffix and must not match."""
        assert not pl._matches("TBA4470000", "447", exact=False)

    def test_suffix_does_not_straddle_the_comma(self):
        """THE bug this guards. Joined as 'TBA...447,TBA9...', a needle spanning
        the boundary passes the SQL ILIKE — Python must reject it per element."""
        joined = ["TBA111447", "TBA999888"]
        needle = "447,TBA9"
        assert ",".join(joined).upper().find(needle) != -1, "fixture must straddle"
        assert not any(pl._matches(t, needle, exact=False) for t in joined)

    def test_exact_requires_the_whole_tba(self):
        assert pl._matches("TBA303912345447", "TBA303912345447", exact=True)
        assert not pl._matches("TBA303912345447", "447", exact=True)


class TestHolderResolution:
    """current_holder is resolved from the most specific trace, so a delivered
    package reports its deliverer rather than whoever the route was assigned to.
    """

    def test_delivered_wins_over_assigned(self):
        """Assert the ASSIGNMENT order of holder_basis, not incidental mentions
        of the same strings elsewhere in the function (my first version of this
        test matched a status filter and failed for the wrong reason)."""
        src = inspect.getsource(pl.lookup_package)
        order = [line.split('holder_basis = ')[1].strip()
                 for line in src.splitlines() if 'holder_basis = "' in line]
        assert order == ['"delivered"', '"in_progress"', '"assigned"', '"exception"'], \
            f"holder precedence changed: {order}"

    def test_minimum_suffix_length_is_enforced(self):
        """A 1-char needle would match nearly every package."""
        assert pl._MIN_SUFFIX >= 4


class TestPrivacy:
    def test_no_address_field_on_any_trace(self):
        """Dimension 7: no addresses in output schemas. ADR-219 nulls them 48h
        post-route anyway, so a TBA is the only durable identifier."""
        from app.schemas.package_lookup import (
            AssignmentTrace, DeliveryTrace, ExceptionTrace, PackageTimeline,
        )
        for M in (AssignmentTrace, DeliveryTrace, ExceptionTrace, PackageTimeline):
            for f in M.model_fields:
                assert "address" not in f, f"{M.__name__}.{f} leaks an address"
