"""The dispatch performance card must not derive metrics from an ADDRESS count (ADR-298).

THE DEFECT. `DispatchPerformanceSummary` built `baseline_minutes_per_package`,
`baseline_sample_size` and `slowest_routes` from `Route.package_count`. In
workforce mode that column counts captain-entered ADDRESSES, not parcels — a
route holding one tote with three addresses reports 3 while the tote physically
carries fifty. `slowest_routes` is the one that causes action: a dispatcher
reading a ranked list of underperforming routes has every reason to intervene,
and in workforce mode that ranking was computed against a baseline with no
meaning.

WHY ADR-294'S GUARD MISSED IT. That guard reasoned about `DeliveryStop` being
EMPTY in workforce mode — an absent table, which fails safe because a query over
it returns nothing. `Route.package_count` is `nullable=False, default=0` and IS
populated, with a number in the wrong unit. An empty table fails safe; a
populated column with the wrong unit does not.
"""
import inspect

from app.schemas.dashboard_summaries import DispatchPerformanceSummary
from app.services import dashboard_summaries as D


# ── D5: the guard exists, and is separate from the DeliveryStop one ───────────

def test_a_named_guard_exists_beside_the_existing_one():
    """D5 — a helper, not an `if` at each call site.

    Scattered ifs are what produced this defect: ADR-294 guarded the sites it
    knew about and the next site added inherited nothing.
    """
    assert callable(D._route_package_metrics_available)
    assert callable(D._package_totals_for_mode)


def test_the_guard_reasons_about_the_wrong_unit_not_an_empty_table():
    """The two guards answer different questions and must not be collapsed."""
    src = inspect.getsource(D._route_package_metrics_available)
    assert "operating_mode" in src
    assert "MODE_FULL" in src
    # A missing config must fail CLOSED — same direction as RequireMode.
    assert "cfg is not None" in src


# ── D1: package_count no longer reaches the card ──────────────────────────────

def test_every_package_count_derivation_is_gated():
    """The regression. `package_count` may still be READ, but never divided by
    or ranked on without the guard first."""
    src = inspect.getsource(D.get_dispatch_dashboard_summary)
    assert "pkg_metrics_ok = _route_package_metrics_available(" in src
    # The three derived figures are all behind it.
    assert "if pkg_metrics_ok:" in src
    assert "if pkg_metrics_ok else []" in src


def test_the_lean_card_reads_flex_package_count_not_package_count():
    """D1 — workforce mode carries less signal, not none.

    Every package figure on the lean card comes from `flex_package_count`, the
    real parcel count a captain reads off Amazon Flex at scan time.
    """
    src = inspect.getsource(D.get_dispatch_dashboard_summary)
    lean = src[src.index("lean: dict = {}"):src.index("performance = DispatchPerformanceSummary")]
    assert "flex_package_count" in lean
    assert "Route.package_count" not in lean, (
        "the lean card must never read package_count — it counts ADDRESSES"
    )


def test_a_partial_scan_makes_the_total_null_not_a_partial_sum():
    """ADR-299 D4 applied here: summing only the scanned routes silently
    reports a smaller day. NULL plus an unscanned count is honest."""
    src = inspect.getsource(D.get_dispatch_dashboard_summary)
    assert "if not missing_count else None" in src
    assert "routes_missing_flex_count" in src


# ── D3: the reason is carried at the card ─────────────────────────────────────

def test_the_card_carries_its_own_availability_flag():
    """A client inferring unavailability from `baseline is None` is wrong the
    first time a full-mode company has no completed routes in 30 days."""
    f = DispatchPerformanceSummary.model_fields
    assert "available" in f
    assert "unavailable_reason" in f
    assert f["available"].default is True


def test_no_schema_change_was_needed_for_the_nulls():
    """The tell that ADR-294 already chose the right shape: the fields that go
    NULL were already Optional."""
    f = DispatchPerformanceSummary.model_fields
    assert "Optional" in str(f["baseline_minutes_per_package"].annotation)
    # baseline_sample_size stays a plain int — zero samples qualified is an
    # honest measurement of OUR data, not a claim about the crew.
    assert f["baseline_sample_size"].annotation is int


def test_lean_metrics_are_all_nullable():
    """Every lean metric can be absent (no closed routes, no scan yet), so none
    may be a non-Optional int that would default to a misleading 0."""
    f = DispatchPerformanceSummary.model_fields
    for name in (
        "routes_completed", "packages_carried", "mean_packages_per_route",
        "mean_blocks_per_route", "mean_totes_per_route",
        "capacity_utilisation_pct", "rts_per_100_carried",
        "missing_per_100_carried", "routes_missing_flex_count",
    ):
        assert "Optional" in str(f[name].annotation), f"{name} must be Optional"
        assert f[name].default is None, f"{name} must default to None, never 0"


# ── D4: the accidentally-safe sites are now safe on purpose ───────────────────

def test_rts_completion_is_gated_rather_than_reporting_zero_percent():
    """It reported completion=0% in workforce mode — a zero that reads as a
    measurement when the truth is "we do not track that here"."""
    src = inspect.getsource(D.get_dispatch_dashboard_summary)
    assert "rt.package_count and _route_package_metrics_available(db, company_id)" in src


def test_crew_performance_is_gated_too():
    """Correct only because a join finds nothing — a property that expires
    silently the day DeliveryStop is written for any reason."""
    src = inspect.getsource(D.get_dispatch_dashboard_summary)
    crew = src[src.index("crew_rows = ("):src.index("crew_names =")]
    assert "if pkg_metrics_ok else []" in crew
