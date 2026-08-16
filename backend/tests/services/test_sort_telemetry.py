"""Sort-decision telemetry (ADR-273).

Pins the three composition metrics against shapes taken from the real Morgan
2026-08-15 sort, so a regression in the measurement is caught before it silently
misreports an algorithm change.
"""
import pytest
from uuid import uuid4

from app.services.sort_telemetry import (
    compute_sort_metrics,
    _block_adjacency,
    RUNT_TOTE_THRESHOLD,
)
from app.services.sort_tuning import (
    SortTuning,
    resolve_sort_tuning,
    MODE_GROUP_FIRST,
    MODE_BLOCK_COMPLETION,
    DEFAULT_W_TIME,
    DEFAULT_WALK_BUDGET_M,
)


class _Route:
    """Minimal stand-in for the Route ORM row the metrics read."""

    def __init__(self, blocks, totes, slot_cost=12, capacity_limit=12,
                 package_count=50, closed_reason=None):
        self.block_keys = blocks
        self.tote_ids = totes
        self.slot_cost = slot_cost
        self.capacity_limit = capacity_limit
        self.package_count = package_count
        self.closed_reason = closed_reason


# ── adjacency ────────────────────────────────────────────────────────────────

def test_same_street_adjacent_hundred_is_an_edge():
    adj = _block_adjacency(["W_40_St_100", "W_40_St_200"])
    assert adj["W_40_St_100"] == {"W_40_St_200"}


def test_two_hundred_gap_is_not_an_edge():
    """W_55_400 <-> W_55_600 differ by 200 — the ADR-234 field report."""
    adj = _block_adjacency(["W_55_St_400", "W_55_St_600"])
    assert not adj.get("W_55_St_400")


def test_parallel_street_same_hundred_is_an_edge():
    adj = _block_adjacency(["W_31_St_300", "W_32_St_300"])
    assert adj["W_31_St_300"] == {"W_32_St_300"}


def test_five_streets_apart_is_not_an_edge():
    adj = _block_adjacency(["W_50_St_100", "W_55_St_100"])
    assert not adj.get("W_50_St_100")


def test_named_and_sentinel_blocks_get_no_structural_edges():
    """Broadway_700 and __unknown_* have no direction/type triple to compare."""
    adj = _block_adjacency(["Broadway_700", "__unknown_TBA1", "W_40_St_100"])
    assert not adj.get("Broadway_700")
    assert not adj.get("__unknown_TBA1")


# ── orphan blocks ────────────────────────────────────────────────────────────

def test_live_morgan_route_2_is_all_orphans():
    """The reported route: W_46_St_100, W_51_St_400, 7_Ave_700 — no pair adjacent."""
    m = compute_sort_metrics(
        [_Route(["W_46_St_100", "W_51_St_400", "7_Ave_700"], ["a", "b", "c", "d"])]
    )
    assert m["orphan_blocks"] == 3


def test_single_block_route_cannot_orphan():
    m = compute_sort_metrics([_Route(["W_46_St_100"], ["a", "b", "c", "d"])])
    assert m["orphan_blocks"] == 0


def test_adjacent_pair_is_not_an_orphan():
    m = compute_sort_metrics([_Route(["W_40_St_100", "W_40_St_200"], ["a", "b"])])
    assert m["orphan_blocks"] == 0


# ── splits, runts, capacity ──────────────────────────────────────────────────

def test_block_on_two_routes_counts_as_split():
    m = compute_sort_metrics([
        _Route(["W_46_St_100"], ["a", "b", "c"]),
        _Route(["W_46_St_100"], ["d", "e"]),
    ])
    assert m["blocks_split"] == 1


def test_runt_threshold_is_inclusive():
    m = compute_sort_metrics([
        _Route(["W_40_St_100"], ["a"] * RUNT_TOTE_THRESHOLD),
        _Route(["W_43_St_500"], ["b"] * (RUNT_TOTE_THRESHOLD + 1)),
    ])
    assert m["runt_routes"] == 1


def test_capacity_util_uses_each_routes_own_limit():
    """A paired route's higher lock must not be divided by the standard one."""
    m = compute_sort_metrics([
        _Route(["W_40_St_100"], ["a"], slot_cost=18, capacity_limit=18),
        _Route(["W_43_St_500"], ["b"], slot_cost=6, capacity_limit=12),
    ])
    assert m["capacity_util_pct"] == pytest.approx(80.0)   # (18+6)/(18+12)


def test_routes_with_no_capacity_recorded_are_skipped_not_zeroed():
    m = compute_sort_metrics([
        _Route(["W_40_St_100"], ["a"], slot_cost=12, capacity_limit=12),
        _Route(["W_43_St_500"], ["b"], slot_cost=0, capacity_limit=0),
    ])
    assert m["capacity_util_pct"] == pytest.approx(100.0)


def test_histograms_and_unrecorded_close_reason():
    m = compute_sort_metrics([
        _Route(["W_40_St_100"], ["a"], closed_reason="group_complete"),
        _Route(["W_43_St_500", "W_43_St_600"], ["b", "c"]),
    ])
    assert m["blocks_per_route_hist"] == {"1": 1, "2": 1}
    assert m["closed_reason_hist"] == {"group_complete": 1, "unrecorded": 1}


def test_empty_sort_does_not_crash():
    m = compute_sort_metrics([])
    assert m["routes_out"] == 0
    assert m["capacity_util_pct"] is None


def test_null_arrays_are_tolerated():
    """Rows predating the columns carry NULL, not []."""
    r = _Route(None, None)
    m = compute_sort_metrics([r])
    assert m["routes_out"] == 1
    assert m["blocks_in"] == 0


# ── tuning resolution ────────────────────────────────────────────────────────

def test_default_tuning_names_the_shipped_algorithm():
    assert SortTuning().algorithm_version == "block_completion_v1"


def test_group_first_gets_its_own_version_string():
    """Two modes must not pool into one comparable population."""
    assert SortTuning(assembly_mode=MODE_GROUP_FIRST).algorithm_version == "group_first_v1"


def test_weight_change_does_not_split_the_version():
    """A weight sweep stays inside one population; the weights are their own columns."""
    assert SortTuning(w_time=2.5).algorithm_version == SortTuning().algorithm_version


def test_telemetry_subset_is_the_weights_and_guards():
    t = SortTuning().as_telemetry()
    assert t["w_time"] == DEFAULT_W_TIME
    assert t["walk_budget_m"] == DEFAULT_WALK_BUDGET_M
    assert "assembly_mode" not in t   # recorded via algorithm_version instead


class _StubCfg:
    """Stand-in for a CompanyConfig row. Avoids the DB entirely: the JSONB
    columns on the telemetry tables cannot be created under the SQLite test
    engine, and resolve_sort_tuning only ever reads attributes."""

    def __init__(self, **overrides):
        for f in (
            "sort_w_dense", "sort_w_time", "sort_w_diff", "sort_w_doorman",
            "sort_walk_budget_m", "sort_span_cap_m", "sort_max_consecutive_no_fit",
            "sort_f5_load_floor_hs", "sort_f5_max_hops", "sort_f5_walk_radius_km",
            "route_assembly_mode",
        ):
            setattr(self, f, None)
        for k, v in overrides.items():
            setattr(self, k, v)


class _StubDB:
    """Minimal query(...).filter(...).first() chain returning a fixed config."""

    def __init__(self, cfg):
        self._cfg = cfg

    def query(self, *_a, **_kw):
        return self

    def filter(self, *_a, **_kw):
        return self

    def first(self):
        return self._cfg


def test_missing_config_falls_back_to_defaults():
    """A tenant with no CompanyConfig row must still sort, not 500."""
    assert resolve_sort_tuning(_StubDB(None), uuid4()) == SortTuning()


def test_unknown_assembly_mode_fails_closed():
    """An unrecognised value must never select an experimental branch."""
    db = _StubDB(_StubCfg(route_assembly_mode="experimental_nonsense"))
    assert resolve_sort_tuning(db, uuid4()).assembly_mode == MODE_BLOCK_COMPLETION


def test_configured_values_override_defaults():
    db = _StubDB(_StubCfg(sort_w_time=2.25, route_assembly_mode=MODE_GROUP_FIRST))
    t = resolve_sort_tuning(db, uuid4())
    assert t.w_time == 2.25
    assert t.assembly_mode == MODE_GROUP_FIRST
    # Unset fields still fall back.
    assert t.walk_budget_m == DEFAULT_WALK_BUDGET_M


def test_zero_is_honoured_not_treated_as_unset():
    """`or` would silently swallow a deliberate 0 — _pick uses `is None`."""
    db = _StubDB(_StubCfg(sort_w_doorman=0.0))
    assert resolve_sort_tuning(db, uuid4()).w_doorman == 0.0
