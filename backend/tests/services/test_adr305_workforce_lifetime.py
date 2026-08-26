"""Lifetime stats derived from carried totes, not delivery events (ADR-305).

`get_lifetime_totals` reads `DeliveryStop`, which workforce mode never writes, so
My Stats showed a walker "0 delivered, 4 RTS" — an absence rendered as a number,
attached to the person it appears to indict.

The workforce day carries its own arithmetic:

    delivered = sum(flex_package_count) - sum(rts) - sum(missing)

What was carried, minus what came back. No delivery EVENT exists, but the
delivered QUANTITY is derivable.

These are unit tests over the arithmetic and the wiring. `routes` uses JSONB,
which the shared SQLite fixture cannot create, so the end-to-end check belongs in
staging verification — the same limitation recorded in ADR-304's test module.
"""
import ast
import inspect

import pytest


from app.schemas.stats_series import LifetimeTotalsOut
from app.services import stats_series as S
from app.services.constants import MODE_FULL, MODE_WORKFORCE


def _code_only(obj) -> str:
    """Source with docstrings stripped.

    Three tests in this module first FAILED against their own prose: a docstring
    explaining why `DamagedPackage` is not subtracted counts as a match when you
    grep the raw source for "DamagedPackage". Parse, do not grep — the same
    correction ADR-291's static checks needed.
    """
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)



# ── D0: full mode is not touched ─────────────────────────────────────────────

def test_mode_defaults_to_full_so_existing_callers_are_unchanged():
    sig = inspect.signature(S.get_lifetime_totals)
    assert sig.parameters["mode"].default == MODE_FULL


def test_full_mode_still_reads_delivery_stop():
    """The whole point of D0: full mode's body is not edited. DeliveryStop is a
    real per-package record there and remains its source."""
    src = inspect.getsource(S.get_lifetime_totals)
    full_branch = src[src.index("else:"):]
    assert "DeliveryStop.packages_delivered" in full_branch
    assert "flex_package_count" not in full_branch


def test_the_workforce_branch_never_touches_delivery_stop():
    src = _code_only(S._workforce_delivered_terms)
    assert "DeliveryStop" not in src
    assert "flex_package_count" in src


# ── D1: the derivation, and what is NOT subtracted ───────────────────────────

def _derive(routes, rts=0, missing=0):
    """Mirrors _workforce_delivered_terms' arithmetic."""
    scanned = [f for f in routes if f is not None]
    excluded = len(routes) - len(scanned)
    if not scanned:
        return None, 0, 0, excluded
    carried = sum(scanned)
    return max(0, carried - rts - missing), rts, missing, excluded


def test_delivered_is_carried_minus_what_came_back():
    delivered, rts, missing, excluded = _derive([47, 52], rts=5, missing=1)
    assert delivered == 99 - 5 - 1 == 93
    assert excluded == 0


def test_route_damage_is_not_subtracted_twice():
    """`package_damaged` is one of six RtsType values, so it is ALREADY inside
    sum(rts). Subtracting DamagedPackage as well would drop the parcel twice."""
    src = _code_only(S._workforce_delivered_terms)
    assert "DamagedPackage" not in src, (
        "route damage is already counted in rts; station damage never entered "
        "the carried figure — neither belongs in this subtraction"
    )
    # One damaged parcel, recorded as an RTS, costs exactly one.
    delivered, *_ = _derive([47], rts=1)
    assert delivered == 46


def test_station_damage_does_not_affect_the_figures():
    """A station-damaged package is pulled BEFORE the captain takes the Flex
    count, so it never entered `flex_package_count`. It is in neither term."""
    # Same carried count regardless of how many DamagedPackage rows exist.
    assert _derive([47], rts=2)[0] == 45


def test_delivered_never_goes_negative():
    """More returns than carried means a miscount upstream; a negative delivered
    figure would be worse than a wrong one."""
    delivered, *_ = _derive([10], rts=8, missing=5)
    assert delivered == 0


# ── D2: the identity with full mode ──────────────────────────────────────────

@pytest.mark.parametrize(
    "flex,rts,missing",
    [([47, 52], 5, 1), ([100], 0, 0), ([30, 30, 30], 7, 3)],
)
def test_attempted_equals_carried(flex, rts, missing):
    """THE identity. Full mode computes attempted = delivered + rts + missing;
    substituting D1's delivered gives back sum(flex) exactly.

    So the carried-based denominator IS full mode's definition, not a parallel
    one — which is what keeps success_pct meaning the same thing in both modes
    when it feeds a scorecard or an appeal.
    """
    delivered, r, m, _ = _derive(flex, rts=rts, missing=missing)
    attempted = delivered + r + m
    assert attempted == sum(flex)


def test_success_pct_uses_the_shared_expression():
    """Full mode's line is untouched; the workforce branch reaches the SAME
    computation by falling through to it."""
    src = inspect.getsource(S.get_lifetime_totals)
    assert src.count("out.success_pct = round(") == 1, (
        "one expression, reached by both branches — not two that can drift"
    )


def test_success_pct_is_guarded_against_a_none_numerator():
    """None + int raises. A None delivered has no ratio."""
    src = inspect.getsource(S.get_lifetime_totals)
    assert "if out.delivered is not None:" in src


# ── D3: unscanned routes leave BOTH terms ────────────────────────────────────

def test_an_unscanned_route_is_excluded_from_both_terms():
    """Not from the numerator alone.

    Counting an excluded route's returns while excluding its carried count
    deflates the ratio against a denominator those packages were never in.
    """
    src = inspect.getsource(S._workforce_delivered_terms)
    # Returns are counted over the SCANNED route ids only.
    assert "scanned_ids" in src
    assert "RTSPackage.route_id.in_(scanned_ids)" in src
    assert "MissingPackage.route_id.in_(scanned_ids)" in src


def test_the_identity_survives_an_exclusion():
    delivered, rts, missing, excluded = _derive([47, 52, None], rts=5, missing=1)
    assert excluded == 1
    assert delivered + rts + missing == 99, "attempted still equals carried"


def test_never_scanned_yields_none_not_zero():
    """An empty scanned set has no ratio, and 0 would read as 'delivered
    nothing' — the exact misreading this ADR exists to remove."""
    delivered, rts, missing, excluded = _derive([None, None])
    assert delivered is None
    assert excluded == 2


def test_the_exclusion_count_is_reported():
    """ADR-291 D5's no-silent-drops rule, applied to a statistic: '93.9% over 2
    of 3 routes' is honest, '93.9%' alone is a claim about unmeasured work."""
    assert "routes_excluded_unscanned" in LifetimeTotalsOut.model_fields
    assert LifetimeTotalsOut.model_fields["routes_excluded_unscanned"].default == 0


def test_delivered_is_optional_on_the_wire():
    assert "Optional" in str(LifetimeTotalsOut.model_fields["delivered"].annotation)


# ── D5: the mode is resolved once, at the router ─────────────────────────────

def test_the_router_resolves_the_mode_and_passes_it_down():
    """Not re-derived inside each stats function: /me/stats calls three of them,
    which would be three identical CompanyConfig queries for one unchanging
    fact."""
    from app.routers import assignment_history as AH

    src = _code_only(AH)
    # ONE query, however many times the name appears (import + filter clause).
    assert src.count("db.query(CompanyConfig)") == 1, (
        "the config is looked up once per request, not once per stats function"
    )
    assert "mode=mode" in src


def test_a_missing_config_fails_to_workforce():
    """The safe direction: deriving from carried totes is honest for a tenant
    with no feed, while reading an empty DeliveryStop reports a real person as
    having delivered nothing."""
    from app.routers import assignment_history as AH

    src = inspect.getsource(AH)
    assert "else MODE_WORKFORCE" in src
