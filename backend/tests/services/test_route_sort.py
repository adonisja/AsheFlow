"""
Tests for route_sort.py — the walker route distribution algorithm.

Covers:
  - derive_block_key: address parsing (directional, non-directional, noise stripping)
  - _build_adjacency_graph: BFS cross-street adjacency (replaces _block_key_adjacent)
  - _haversine_km: distance sanity checks
  - _resolve_effort_class: weighted package-aware scoring (address_workloads + difficulty_flags)
  - _pair_ovs: half-slot OV cost accumulation
  - run_sort: end-to-end — capacity enforcement, BFS clustering, misroute detection,
              no address data in output, empty input, oversize block
"""
import uuid
from datetime import date

import pytest

from app.services.derive_block_key import derive_block_key, ParsedBlock, UnparseableAddress
from app.services.route_sort import (
    _build_adjacency_graph,
    _haversine_km,
    _resolve_effort_class,
    _pair_ovs,
    _Tote,
    _Package,
    run_sort,
)
from app.schemas.walker_routes import (
    PackageInput,
    SortRequest,
    EFFORT_CAPACITY,
    OV_HALF_SLOTS,
    TOTE_HALF_SLOTS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TA_ID = uuid.uuid4()
_DATE = date.today()


def _request(packages: list[PackageInput]) -> SortRequest:
    return SortRequest(
        truck_assignment_id=_TA_ID,
        route_date=_DATE,
        packages=packages,
    )


def _pkg(
    tba: str,
    address: str,
    bag_id: str,
    lat: float = 40.75,
    lng: float = -73.99,
    package_type: str | None = None,
    first_cross_street: str | None = None,
    second_cross_street: str | None = None,
    normalised_address: str | None = None,
) -> PackageInput:
    parsed = derive_block_key(address, tba=tba)
    block_key = parsed.block_key if isinstance(parsed, ParsedBlock) else None
    return PackageInput(
        tba_number=tba,
        bag_id=bag_id,
        block_key=block_key,
        package_type=package_type,
        lat=lat,
        lng=lng,
        first_cross_street=first_cross_street,
        second_cross_street=second_cross_street,
        normalised_address=normalised_address,
    )


def _make_tote(bag_id: str, block_key: str) -> _Tote:
    t = _Tote(bag_id=bag_id)
    t.packages.append(_Package(
        tba_number=f"TBA_{bag_id}", bag_id=bag_id,
        block_key=block_key, lat=40.75, lng=-73.99,
    ))
    return t


# ---------------------------------------------------------------------------
# derive_block_key (canonical — from derive_block_key.py)
# ---------------------------------------------------------------------------

def _bk(address: str) -> str | None:
    """Unwrap ParsedBlock.block_key, or return None for UnparseableAddress."""
    result = derive_block_key(address, tba="test")
    return result.block_key if isinstance(result, ParsedBlock) else None


class TestDeriveBlockKey:
    def test_directional_street(self):
        # 350 → hundred floor 300, no side
        assert _bk("350 W 36th St") == "W_36_St_300"

    def test_directional_odd(self):
        # 351 → same hundred block as 350: W_36_St_300
        assert _bk("351 W 36th St") == "W_36_St_300"

    def test_non_directional(self):
        assert _bk("410 5th Ave") == "5_Ave_400"

    def test_ordinal_suffix_stripped(self):
        assert _bk("410 W 37th St") == "W_37_St_400"

    def test_noise_stripped(self):
        assert _bk("350 W 36th St APT 4B") == "W_36_St_300"

    def test_hundred_boundary(self):
        # 399 → floors to 300
        assert _bk("399 W 36th St") == "W_36_St_300"

    def test_400s(self):
        # 415 → floors to 400
        assert _bk("415 W 37th St") == "W_37_St_400"

    def test_unparseable_no_house_number(self):
        assert isinstance(derive_block_key("Somewhere over the rainbow", tba="t"), UnparseableAddress)

    def test_empty_string(self):
        assert isinstance(derive_block_key("", tba="t"), UnparseableAddress)

    def test_unknown_street_type(self):
        assert isinstance(derive_block_key("350 W 36th Pkwy", tba="t"), UnparseableAddress)

    def test_avenue_alias(self):
        assert _bk("410 W 36th Avenue") == "W_36_Ave_400"

    def test_uppercase_street_type(self):
        # GeoClient returns uppercase: "433 W 32 ST" → floors to 400
        assert _bk("433 W 32 ST") == "W_32_St_400"

    def test_uppercase_ave(self):
        assert _bk("433 W 9 AVE") == "W_9_Ave_400"


# ---------------------------------------------------------------------------
# _build_adjacency_graph (replaces _block_key_adjacent)
# BFS uses a weighted adjacency graph; these tests verify edge costs
# ---------------------------------------------------------------------------

class TestBuildAdjacencyGraph:
    def _graph(self, block_to_totes: dict) -> dict:
        return _build_adjacency_graph(block_to_totes)

    def _tote(self, bk: str, first_cs: str | None = None, second_cs: str | None = None) -> list[_Tote]:
        t = _Tote(bag_id=bk)
        t.packages.append(_Package(
            tba_number=f"T_{bk}", bag_id=bk, block_key=bk,
            lat=40.75, lng=-73.99,
            first_cross_street=first_cs,
            second_cross_street=second_cs,
        ))
        return [t]

    def test_cross_street_adjacency_cost_1(self):
        # W 32 St 400 block borders 9 Ave — any block ON 9 Ave gets cost 1
        b2t = {
            "W_32_St_400": self._tote("W_32_St_400", first_cs="9 AVENUE"),
            "W_9_Ave_400": self._tote("W_9_Ave_400"),
        }
        graph = self._graph(b2t)
        neighbours = {bk: cost for bk, cost in graph.get("W_32_St_400", [])}
        assert "W_9_Ave_400" in neighbours
        assert neighbours["W_9_Ave_400"] == 1

    def test_adjacent_hundred_range_cost_2(self):
        # W_36_St_300 ↔ W_36_St_400 — differ by 100 → cost 2
        b2t = {
            "W_36_St_300": self._tote("W_36_St_300"),
            "W_36_St_400": self._tote("W_36_St_400"),
        }
        graph = self._graph(b2t)
        neighbours = {bk: cost for bk, cost in graph.get("W_36_St_300", [])}
        assert "W_36_St_400" in neighbours
        assert neighbours["W_36_St_400"] == 2

    def test_parallel_street_cost_3(self):
        # W_36_St_300 ↔ W_37_St_300 — adjacent street number, same range → cost 3
        b2t = {
            "W_36_St_300": self._tote("W_36_St_300"),
            "W_37_St_300": self._tote("W_37_St_300"),
        }
        graph = self._graph(b2t)
        neighbours = {bk: cost for bk, cost in graph.get("W_36_St_300", [])}
        assert "W_37_St_300" in neighbours
        assert neighbours["W_37_St_300"] == 3

    def test_non_adjacent_streets_no_edge(self):
        # W 36 St and W 57 St — 21 streets apart, no structural edge
        b2t = {
            "W_36_St_300": self._tote("W_36_St_300"),
            "W_57_St_300": self._tote("W_57_St_300"),
        }
        graph = self._graph(b2t)
        neighbours = {bk for bk, _ in graph.get("W_36_St_300", [])}
        assert "W_57_St_300" not in neighbours

    def test_non_contiguous_hundred_range_no_edge(self):
        # W_36_St_300 and W_36_St_500 differ by 200 — no adjacency edge
        b2t = {
            "W_36_St_300": self._tote("W_36_St_300"),
            "W_36_St_500": self._tote("W_36_St_500"),
        }
        graph = self._graph(b2t)
        neighbours = {bk for bk, _ in graph.get("W_36_St_300", [])}
        assert "W_36_St_500" not in neighbours

    def test_graph_is_bidirectional(self):
        # cost-2 edge between 300 and 400 must appear in both directions
        b2t = {
            "W_36_St_300": self._tote("W_36_St_300"),
            "W_36_St_400": self._tote("W_36_St_400"),
        }
        graph = self._graph(b2t)
        fwd = {bk for bk, _ in graph.get("W_36_St_300", [])}
        rev = {bk for bk, _ in graph.get("W_36_St_400", [])}
        assert "W_36_St_400" in fwd
        assert "W_36_St_300" in rev

    def test_single_block_no_edges(self):
        b2t = {"W_36_St_300": self._tote("W_36_St_300")}
        graph = self._graph(b2t)
        assert graph.get("W_36_St_300", []) == []


# ---------------------------------------------------------------------------
# _haversine_km
# ---------------------------------------------------------------------------

class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert _haversine_km(40.75, -73.99, 40.75, -73.99) == pytest.approx(0.0, abs=1e-6)

    def test_one_block_approx_80m(self):
        d = _haversine_km(40.750, -73.990, 40.7508, -73.990)
        assert 0.05 < d < 0.15

    def test_half_km_distance(self):
        d = _haversine_km(40.750, -73.990, 40.755, -73.990)
        assert d > 0.25


# ---------------------------------------------------------------------------
# _resolve_effort_class — weighted package-aware scoring
# Signature: (packages, address_workloads, block_workloads, difficulty_flags,
#              t_factor, p_factor) -> (effort_class, source, score, coverage_pct)
# ---------------------------------------------------------------------------

class TestResolveEffortClass:

    def _pkg(self, bk: str, addr: str | None = None) -> _Package:
        return _Package(tba_number="T", bag_id="B", block_key=bk,
                        lat=40.75, lng=-73.99, normalised_address=addr)

    def test_default_when_no_profile_no_flag(self):
        effort, source, score, cov = _resolve_effort_class(
            [self._pkg("W_36_St_300")], {}, {}, {}
        )
        assert effort == "standard"
        assert source == "default"
        assert cov == 0.0

    def test_address_profile_overrides_default(self):
        pkg = self._pkg("W_36_St_300", addr="350 W 36 ST")
        effort, source, score, cov = _resolve_effort_class(
            [pkg], {"350 W 36 ST": "high_wait"}, {}, {}
        )
        assert effort == "heavy"
        assert source == "address_profile"
        assert cov == 1.0

    def test_block_workload_used_when_no_address_match(self):
        pkg = self._pkg("W_36_St_300")
        effort, source, score, cov = _resolve_effort_class(
            [pkg], {}, {"W_36_St_300": "high_touch"}, {}
        )
        assert effort == "heavy"
        assert source == "block_profile"
        assert cov == 0.0

    def test_difficulty_flag_overrides_address_profile(self):
        pkg = self._pkg("W_36_St_300", addr="350 W 36 ST")
        effort, source, score, cov = _resolve_effort_class(
            [pkg],
            {"350 W 36 ST": "standard"},
            {},
            {"W_36_St_300": "heavy"},
        )
        assert effort == "heavy"
        assert source == "flag"

    def test_moderate_flag_maps_to_heavy_effort(self):
        pkg = self._pkg("W_36_St_300")
        effort, source, score, cov = _resolve_effort_class(
            [pkg], {}, {}, {"W_36_St_300": "moderate"}
        )
        assert effort == "heavy"
        assert source == "flag"

    def test_bulk_drop_address_maps_to_standard(self):
        # bulk_drop: tw=0.6, pw=1.4. At default t=p=0.5: 0.6*0.5+1.4*0.5=1.0 → standard
        pkg = self._pkg("W_36_St_300", addr="350 W 36 ST")
        effort, source, score, cov = _resolve_effort_class(
            [pkg], {"350 W 36 ST": "bulk_drop"}, {}, {}
        )
        assert effort == "standard"
        assert cov == 1.0

    def test_empty_package_list_returns_standard(self):
        effort, source, score, cov = _resolve_effort_class([], {}, {}, {})
        assert effort == "standard"
        assert cov == 0.0

    def test_mixed_route_score_is_weighted(self):
        # 1 high_wait pkg + 9 bulk_drop pkgs → weighted toward bulk_drop
        pkgs = [self._pkg("W_36_St_300", addr=f"addr{i}") for i in range(10)]
        addr_workloads = {f"addr{i}": "bulk_drop" for i in range(9)}
        addr_workloads["addr9"] = "high_wait"
        effort, source, score, cov = _resolve_effort_class(
            pkgs, addr_workloads, {}, {}
        )
        # 9 bulk_drop (score ~0.6+0.7=1.3*0.5+1.4*0.5=1.0) + 1 high_wait (2.0*0.5+0.8*0.5=1.4)
        # weighted avg ≈ (9*1.0 + 1*1.4) / 10 = 1.04 → standard (< 1.3)
        assert effort == "standard"
        assert cov == 1.0

    def test_coverage_pct_partial(self):
        # 3 packages: 2 with address matches, 1 without
        pkgs = [
            self._pkg("bk1", addr="addr1"),
            self._pkg("bk1", addr="addr2"),
            self._pkg("bk1"),               # no normalised_address
        ]
        effort, source, score, cov = _resolve_effort_class(
            pkgs, {"addr1": "standard", "addr2": "standard"}, {}, {}
        )
        assert cov == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# _pair_ovs
# ---------------------------------------------------------------------------

class TestPairOvs:
    def _make_tote_with_ov(self, bag_id: str, ov_types: list[str]) -> _Tote:
        tote = _Tote(bag_id=bag_id)
        for i, pt in enumerate(ov_types):
            tote.packages.append(_Package(
                tba_number=f"OV{i}", bag_id=bag_id,
                block_key="W_36_St_300", lat=None, lng=None,
                package_type=pt,
            ))
        return tote

    def test_ov_s_adds_one_half_slot(self):
        totes = {"Bag1": self._make_tote_with_ov("Bag1", ["OV_S"])}
        _pair_ovs(totes)
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["S"]
        assert totes["Bag1"].half_slot_cost == TOTE_HALF_SLOTS + 1

    def test_ov_xl_adds_four_half_slots(self):
        totes = {"Bag1": self._make_tote_with_ov("Bag1", ["OV_XL"])}
        _pair_ovs(totes)
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["XL"]
        assert totes["Bag1"].half_slot_cost == TOTE_HALF_SLOTS + 4

    def test_multiple_ovs_accumulate(self):
        totes = {"Bag1": self._make_tote_with_ov("Bag1", ["OV_M", "OV_L"])}
        _pair_ovs(totes)
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["M"] + OV_HALF_SLOTS["L"]

    def test_standard_package_not_counted_as_ov(self):
        tote = _Tote(bag_id="Bag1")
        tote.packages.append(_Package(
            tba_number="T1", bag_id="Bag1",
            block_key="W_36_St_300", lat=None, lng=None,
            package_type="standard",
        ))
        _pair_ovs({"Bag1": tote})
        assert tote.ov_half_slots == 0


# ---------------------------------------------------------------------------
# run_sort — end-to-end
# Signature: (request, address_workloads, block_workloads, difficulty_flags,
#              t_factor=0.5, p_factor=0.5)
# ---------------------------------------------------------------------------

class TestRunSort:

    def test_empty_input_returns_no_routes(self):
        result = run_sort(_request([]), {}, {}, {})
        assert result.routes == []
        assert result.unassigned_misroutes == []

    def test_single_tote_single_route(self):
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA"),
            _pkg("TBA002", "352 W 36th St", "BagA"),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 1
        assert result.routes[0].route_number == 1
        assert set(result.routes[0].tba_numbers) == {"TBA001", "TBA002"}

    def test_no_address_data_in_output(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {}, {})
        serialised = result.model_dump_json()
        assert "36th" not in serialised
        for route in result.routes:
            for tba in route.tba_numbers:
                assert "36th" not in tba and "St" not in tba
            for tote_id in route.tote_ids:
                assert "36th" not in tote_id

    def test_routes_numbered_from_one(self):
        pkgs_a = [_pkg(f"TBA{i:03}", "350 W 36th St", "BagA", lat=40.750, lng=-73.990) for i in range(3)]
        pkgs_b = [_pkg(f"TBA{i:03}", "800 W 57th St", "BagB", lat=40.770, lng=-73.985) for i in range(100, 103)]
        result = run_sort(_request(pkgs_a + pkgs_b), {}, {}, {})
        route_numbers = [r.route_number for r in result.routes]
        assert route_numbers == sorted(route_numbers)
        assert route_numbers[0] == 1

    def test_capacity_respected_standard(self):
        # 7 totes × 2 half-slots = 14 > 12 capacity — must split
        pkgs = [_pkg(f"TBA{i:03}", f"{350 + i*2} W 36th St", f"Bag{i}", lat=40.750, lng=-73.990) for i in range(7)]
        result = run_sort(_request(pkgs), {}, {}, {})
        total_totes = sum(len(r.tote_ids) for r in result.routes)
        assert total_totes == 7
        assert len(result.routes) >= 1

    def test_heavy_route_has_reduced_capacity(self):
        flags = {"W_36_St_300": "heavy"}
        pkgs = [_pkg(f"TBA{i:03}", "350 W 36th St", f"Bag{i}") for i in range(5)]
        result = run_sort(_request(pkgs), {}, {}, flags)
        assert result.routes[0].effort_class == "heavy"
        assert result.routes[0].capacity_limit == EFFORT_CAPACITY["heavy"]

    def test_bulk_drop_address_profile_yields_standard_effort(self):
        # bulk_drop at default t=p=0.5 scores 1.0 → standard (easy threshold is < 0.8)
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA", normalised_address="350 W 36 ST")]
        result = run_sort(_request(pkgs), {"350 W 36 ST": "bulk_drop"}, {}, {})
        assert result.routes[0].effort_class == "standard"

    def test_flag_overrides_profile_in_route(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA", normalised_address="350 W 36 ST")]
        result = run_sort(
            _request(pkgs),
            {"350 W 36 ST": "standard"},
            {},
            {"W_36_St_300": "heavy"},
        )
        assert result.routes[0].effort_class == "heavy"
        assert result.routes[0].workload_source == "flag"

    def test_coverage_pct_zero_with_no_address_profiles(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.routes[0].coverage_pct == 0.0

    def test_coverage_pct_one_with_full_address_profiles(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA", normalised_address="350 W 36 ST")]
        result = run_sort(_request(pkgs), {"350 W 36 ST": "standard"}, {}, {})
        assert result.routes[0].coverage_pct == 1.0

    def test_effort_score_present(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert isinstance(result.routes[0].effort_score, float)

    def test_adjacent_blocks_cluster_together_via_bfs(self):
        # 300 W 36th St → W_36_St_300, 400 W 36th St → W_36_St_400.
        # abs(300 - 400) == 100 → cost-2 edge; BFS absorbs both when capacity allows.
        pkgs = [
            _pkg("TBA001", "300 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "400 W 36th St", "BagB", lat=40.750, lng=-73.991),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 1
        assert len(result.routes[0].tote_ids) == 2

    def test_opposite_sides_same_block_cluster_together(self):
        # odd and even on same range → same block key (W_36_St_300), always same route
        pkgs = [
            _pkg("TBA001", "351 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "352 W 36th St", "BagB", lat=40.750, lng=-73.993),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 1
        assert set(result.routes[0].tba_numbers) == {"TBA001", "TBA002"}

    def test_far_apart_streets_split_into_separate_routes(self):
        # W 36th St and W 57th St — 21 streets apart, no BFS edge
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.769, lng=-73.984),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 2

    def test_ov_cost_included_in_slot_cost(self):
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA"),
            _pkg("TBA_OV", "350 W 36th St", "BagA", package_type="OV_XL"),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.routes[0].slot_cost == TOTE_HALF_SLOTS + OV_HALF_SLOTS["XL"]

    def test_misroute_detected_wrong_bag(self):
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagB", lat=40.750, lng=-73.993),
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
            _pkg("TBA003", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert "TBA001" in [m.tba_number for m in result.unassigned_misroutes]

    def test_misroute_has_destination_block_key(self):
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagB", lat=40.750, lng=-73.993),
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
            _pkg("TBA003", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        m = next(x for x in result.unassigned_misroutes if x.tba_number == "TBA001")
        assert m.destination_block_key == "W_36_St_300"
        assert m.current_bag_id == "BagB"

    def test_oversize_single_block_gets_own_route(self):
        pkgs = [_pkg(f"TBA{i:03}", "350 W 36th St", f"Bag{i}") for i in range(8)]
        result = run_sort(_request(pkgs), {}, {}, {})
        all_tba = [tba for r in result.routes for tba in r.tba_numbers]
        assert len(all_tba) == 8

    def test_result_truck_assignment_id_preserved(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.truck_assignment_id == _TA_ID

    def test_result_route_date_preserved(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.route_date == _DATE

    def test_slot_cost_never_exceeds_capacity_for_normal_blocks(self):
        pkgs = [_pkg(f"TBA{i:03}", f"{350+i*2} W 36th St", f"Bag{i}") for i in range(6)]
        result = run_sort(_request(pkgs), {}, {}, {})
        for r in result.routes:
            assert r.slot_cost <= r.capacity_limit


# ---------------------------------------------------------------------------
# BFS clustering properties
# (replaces the old linear segment-window tests)
# ---------------------------------------------------------------------------

class TestBFSClustering:
    """
    BFS expands from the densest seed using edge costs:
      1 = cross-street adjacency (via first/second_cross_street)
      2 = adjacent hundred-block range on same street
      3 = parallel adjacent street

    Block key format: W_36_St_300 (hundred floor, no side).
    Both sides of a block share one key — no cost-0 odd↔even edge.

    These tests verify BFS grouping behaviour — replacing the old 3-segment
    window tests coupled to the removed linear Phase 2a/2b model.
    """

    def test_same_hundred_block_clusters_together(self):
        # 351 and 352 both floor to W_36_St_300 — same block key, always one route
        pkgs = [
            _pkg("TBA001", "351 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "352 W 36th St", "BagB", lat=40.750, lng=-73.993),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 1
        assert set(result.routes[0].tba_numbers) == {"TBA001", "TBA002"}

    def test_three_contiguous_ranges_cluster_together(self):
        # 300s, 400s, 500s on W 36 St — adjacent hundred-block cost-2 edges
        # 5 totes × 2 half-slots = 10 ≤ 12 capacity, all fit in one route
        pkgs = [
            _pkg("TBA001", "301 W 36th St", "Bag1", lat=40.750, lng=-73.995),
            _pkg("TBA002", "302 W 36th St", "Bag2", lat=40.750, lng=-73.995),
            _pkg("TBA003", "401 W 36th St", "Bag3", lat=40.750, lng=-73.992),
            _pkg("TBA004", "402 W 36th St", "Bag4", lat=40.750, lng=-73.992),
            _pkg("TBA005", "502 W 36th St", "Bag5", lat=40.750, lng=-73.989),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        all_tbas = {tba for r in result.routes for tba in r.tba_numbers}
        assert all_tbas == {"TBA001", "TBA002", "TBA003", "TBA004", "TBA005"}
        # 10 half-slots total — fits in one route
        assert len(result.routes) == 1

    def test_all_packages_present_in_output_regardless_of_split(self):
        # 8 totes on the same block — oversize, will split but all must appear
        pkgs = [_pkg(f"TBA{i:03}", "350 W 36th St", f"Bag{i}") for i in range(8)]
        result = run_sort(_request(pkgs), {}, {}, {})
        all_tba = {tba for r in result.routes for tba in r.tba_numbers}
        assert all_tba == {f"TBA{i:03}" for i in range(8)}

    def test_cross_street_adjacency_clusters_via_first_cross_street(self):
        # W 32 St and 9 Ave intersect — if packages on W 32 St declare
        # first_cross_street="9 AVENUE" and 9 Ave block is present,
        # BFS should connect them at cost 1.
        pkgs = [
            _pkg("TBA001", "433 W 32nd St", "BagA",
                 lat=40.750, lng=-73.993, first_cross_street="9 AVENUE"),
            _pkg("TBA002", "433 W 9 Ave",   "BagB",
                 lat=40.750, lng=-73.991),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        # These two blocks are cost-1 neighbours — both fit in capacity, one route
        assert len(result.routes) == 1

    def test_capacity_cap_still_splits_even_with_adjacency(self):
        # W_36_St_300 (6 totes = 12 half-slots, exactly at capacity) and W_36_St_400
        # (1 tote = 2 half-slots) are cost-2 adjacent. Adding W_36_St_400 would push
        # the route to 14 > 12 — BFS must reject it, producing 2 separate routes.
        pkgs_a = [_pkg(f"TBA{i:03}", "300 W 36th St", f"BagA{i}") for i in range(6)]
        pkgs_b = [_pkg("TBA099", "400 W 36th St", "BagB0")]
        result = run_sort(_request(pkgs_a + pkgs_b), {}, {}, {})
        assert len(result.routes) >= 2
        total = sum(len(r.tote_ids) for r in result.routes)
        assert total == 7
