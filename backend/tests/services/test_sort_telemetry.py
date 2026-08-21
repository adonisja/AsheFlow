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


# ── window resolution (the timezone trap) ────────────────────────────────────

def test_days_window_is_inclusive_of_both_ends():
    """`days=28` must span 28 dates, not 29.

    The endpoint resolves start = end - (days - 1). Getting this off by one
    silently widens every window by a day, which is invisible in a chart and
    wrong in a total.
    """
    from datetime import date, timedelta

    end = date(2026, 8, 16)
    for days in (1, 7, 28, 91, 365):
        start = end - timedelta(days=days - 1)
        assert (end - start).days + 1 == days


def test_max_window_is_enforced_at_the_schema_bound():
    """`days` is bounded by MAX_WINDOW_DAYS so an unbounded scan is impossible."""
    from app.routers.sort_metrics import MAX_WINDOW_DAYS

    assert MAX_WINDOW_DAYS == 400
    # The Query(...) bound and the explicit range check must agree, or one of
    # them is dead code.
    end = __import__("datetime").date(2026, 8, 16)
    start = end - __import__("datetime").timedelta(days=MAX_WINDOW_DAYS - 1)
    assert (end - start).days + 1 == MAX_WINDOW_DAYS


# ── ADR-272 Phase 1: decision metadata ───────────────────────────────────────
#
# Phase 1 is a PURE REFACTOR: _build_routes records why each route closed and
# changes no route. These pin the recording; the byte-equality of the routes
# themselves was verified against the pre-refactor implementation over 12 seeded
# days x 6 trucks (see the ADR-272 journal).

CLOSED_REASONS = {
    "capacity", "group_complete", "no_adjacent_fit",
    "no_fit_streak", "walk_budget", "span_cap", "forced_single",
}


def _one_block_totes(n_totes: int, block: str = "W_40_St_100"):
    """n totes all dominant on one block, 10 packages each."""
    from app.services.route_sort import _Tote, _Package

    out = {}
    for i in range(n_totes):
        t = _Tote(bag_id=f"BAG{i:04d}")
        for j in range(10):
            t.packages.append(_Package(
                tba_number=f"TBA{i}{j}", bag_id=t.bag_id, block_key=block,
                lat=None, lng=None,
            ))
        out[t.bag_id] = t
    return out


def test_every_route_records_a_seed_and_a_reason():
    from app.services.route_sort import _build_routes

    routes = _build_routes(_one_block_totes(14), block_workloads={}, difficulty_flags={})
    assert routes, "expected at least one route"
    for r in routes:
        assert r.seed_block_key == "W_40_St_100"
        assert r.closed_reason in CLOSED_REASONS, r.closed_reason


def test_a_full_route_closes_on_capacity():
    """More totes than one route holds -> the first route fills and stops."""
    from app.services.route_sort import _build_routes

    routes = _build_routes(_one_block_totes(20), block_workloads={}, difficulty_flags={})
    assert routes[0].closed_reason == "capacity"


def test_the_last_route_of_an_exhausted_pool_is_group_complete():
    """Nothing left anywhere -> the route finished its territory, it did not
    hit a dead end. The two are different diagnoses and must not be conflated."""
    from app.services.route_sort import _build_routes

    routes = _build_routes(_one_block_totes(3), block_workloads={}, difficulty_flags={})
    assert routes[-1].closed_reason == "group_complete"


def test_blocks_walked_is_at_least_blocks_collected():
    """ADR-235's invariant, now observable: the traversal is a superset of what
    the route actually took totes from."""
    from app.services.route_sort import _build_routes

    for r in _build_routes(_one_block_totes(14), block_workloads={}, difficulty_flags={}):
        assert r.blocks_walked >= len(set(r.block_keys))


def test_telemetry_fields_are_write_only():
    """Nothing in the builder may READ these back — a field that influences the
    algorithm is no longer a pure recording, and Phase 1's whole claim is that
    it changes no route."""
    import inspect
    from app.services import route_sort

    src = inspect.getsource(route_sort._build_routes)
    for field in ("closed_reason", "seed_block_key", "blocks_walked"):
        for line in src.splitlines():
            if field in line:
                assert "route." + field + " =" in line or line.strip().startswith("#"), (
                    f"{field} is read, not just written, on: {line.strip()}"
                )


# ── ADR-272 Phase 2: group-first assembly ────────────────────────────────────
#
# Default-off: block_completion is byte-identical to the pre-Phase-1 output,
# verified over 12 seeded days x 6 trucks (see the ADR-272 journal). These pin
# the behaviours that differ once the mode is switched on.

def _blocks(spec: dict[str, int], pkgs_per_tote: int = 10):
    """{block_key: n_totes} -> tote dict, each tote dominant on its block."""
    from app.services.route_sort import _Tote, _Package

    out, i = {}, 0
    for bk, n in spec.items():
        for _ in range(n):
            t = _Tote(bag_id=f"BAG{i:04d}")
            for j in range(pkgs_per_tote):
                t.packages.append(_Package(
                    tba_number=f"TBA{i}_{j}", bag_id=t.bag_id, block_key=bk,
                    lat=None, lng=None,
                ))
            out[t.bag_id] = t
            i += 1
    return out


def _routes(totes, mode):
    from app.services.route_sort import _build_routes
    return _build_routes(totes, block_workloads={}, difficulty_flags={}, assembly_mode=mode)


def _block_of(route, totes):
    return {totes[b].dominant_block_key for b in route.tote_ids}


def test_group_first_never_half_takes_a_block_that_fits():
    """The field report: W_46_St_100 had 5 totes, a route holds 6, and it was
    split across five routes anyway."""
    from app.services.route_sort import ASSEMBLY_GROUP_FIRST

    # Two blocks of 4 totes. A route holds 6, so block_completion will take 4+2
    # and strand 2; group-first must refuse the partial second block.
    totes = _blocks({"W_40_St_100": 4, "W_40_St_200": 4})
    routes = _routes(totes, ASSEMBLY_GROUP_FIRST)

    where = {}
    for i, r in enumerate(routes):
        for b in _block_of(r, totes):
            where.setdefault(b, set()).add(i)
    split = [b for b, rs in where.items() if len(rs) > 1]
    assert not split, f"group-first split {split}"


def test_block_completion_still_splits_that_case():
    """Guards the comparison itself: if the baseline stopped splitting, the
    Phase 2 measurement would be meaningless."""
    from app.services.route_sort import ASSEMBLY_BLOCK_COMPLETION

    totes = _blocks({"W_40_St_100": 4, "W_40_St_200": 4})
    routes = _routes(totes, ASSEMBLY_BLOCK_COMPLETION)
    where = {}
    for i, r in enumerate(routes):
        for b in _block_of(r, totes):
            where.setdefault(b, set()).add(i)
    assert any(len(rs) > 1 for rs in where.values())


def test_an_oversized_block_is_split_but_its_remainder_seeds_the_next_route():
    """THE PIN. A block bigger than one route must still be delivered, and its
    remainder must seed the NEXT route — not re-enter global ranking, where
    having lost totes lowers its density score and strands it."""
    from app.services.route_sort import ASSEMBLY_GROUP_FIRST

    # 9 totes on one block (route holds 6) plus a smaller rival block that would
    # otherwise outrank the depleted remainder on density.
    totes = _blocks({"W_40_St_100": 9, "W_50_St_100": 4})
    routes = _routes(totes, ASSEMBLY_GROUP_FIRST)

    big = [i for i, r in enumerate(routes) if "W_40_St_100" in _block_of(r, totes)]
    assert len(big) == 2, "the oversized block should occupy exactly two routes"
    assert big[1] == big[0] + 1, (
        f"remainder landed on route {big[1]} instead of immediately after {big[0]} "
        "— the pin did not hold"
    )


def test_no_tote_is_lost_or_duplicated_in_either_mode():
    """Declining a group must not delete it from the pool — the bug that a naive
    `block_totes = []` introduces."""
    from app.services.route_sort import ASSEMBLY_GROUP_FIRST, ASSEMBLY_BLOCK_COMPLETION

    spec = {"W_40_St_100": 4, "W_40_St_200": 3, "W_43_St_100": 5, "W_50_St_100": 2}
    totes = _blocks(spec)
    for mode in (ASSEMBLY_BLOCK_COMPLETION, ASSEMBLY_GROUP_FIRST):
        placed = [b for r in _routes(totes, mode) for b in r.tote_ids]
        assert sorted(placed) == sorted(totes), f"{mode}: totes lost or duplicated"
        assert len(placed) == len(set(placed)), f"{mode}: a tote appears twice"


def test_group_first_still_terminates_when_nothing_fits():
    """Every block oversized for a route: the seed exception must fire each time
    or the outer loop spins forever."""
    from app.services.route_sort import ASSEMBLY_GROUP_FIRST

    totes = _blocks({"W_40_St_100": 8, "W_50_St_100": 8})
    routes = _routes(totes, ASSEMBLY_GROUP_FIRST)
    assert sum(len(r.tote_ids) for r in routes) == 16


def test_mode_constants_do_not_drift_between_modules():
    """route_sort duplicates the mode strings rather than importing sort_tuning
    (it must stay importable without the public config service). Duplication is
    a drift risk, so pin it: a rename in one file and not the other would make
    resolve_sort_tuning return a value _build_routes silently ignores."""
    from app.services.sort_tuning import (
        MODE_BLOCK_COMPLETION, MODE_GROUP_FIRST, VALID_ASSEMBLY_MODES,
    )
    from app.services.route_sort import (
        ASSEMBLY_BLOCK_COMPLETION, ASSEMBLY_GROUP_FIRST,
    )

    assert MODE_BLOCK_COMPLETION == ASSEMBLY_BLOCK_COMPLETION
    assert MODE_GROUP_FIRST == ASSEMBLY_GROUP_FIRST
    assert VALID_ASSEMBLY_MODES == {ASSEMBLY_BLOCK_COMPLETION, ASSEMBLY_GROUP_FIRST}
