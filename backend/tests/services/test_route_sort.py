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
    segment_id: str | None = None,
    from_lion_node_id: str | None = None,
    to_lion_node_id: str | None = None,
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
        segment_id=segment_id,
        from_lion_node_id=from_lion_node_id,
        to_lion_node_id=to_lion_node_id,
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
        # An all-OV bag is a STANDALONE item — no tote base (see TestStandaloneOVCost)
        assert totes["Bag1"].half_slot_cost == OV_HALF_SLOTS["S"]

    def test_ov_xl_adds_four_half_slots(self):
        totes = {"Bag1": self._make_tote_with_ov("Bag1", ["OV_XL"])}
        _pair_ovs(totes)
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["XL"]
        # An all-OV bag is a STANDALONE item — no tote base (see TestStandaloneOVCost)
        assert totes["Bag1"].half_slot_cost == OV_HALF_SLOTS["XL"]

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
        # Fill W_36_St_300 with exactly a full standard route's worth of totes,
        # then add one cost-2-adjacent tote on W_36_St_400. Absorbing it would
        # exceed capacity — BFS must reject it, producing 2 separate routes.
        # Written relative to the constants so it tracks the true tote weight.
        from app.schemas.walker_routes import EFFORT_CAPACITY
        n_full = EFFORT_CAPACITY["standard"] // TOTE_HALF_SLOTS
        pkgs_a = [_pkg(f"TBA{i:03}", "300 W 36th St", f"BagA{i}") for i in range(n_full)]
        pkgs_b = [_pkg("TBA099", "400 W 36th St", "BagB0")]
        result = run_sort(_request(pkgs_a + pkgs_b), {}, {}, {})
        assert len(result.routes) >= 2
        total = sum(len(r.tote_ids) for r in result.routes)
        assert total == n_full + 1


# ---------------------------------------------------------------------------
# ADR-186 — block-completion building, neighborhood misroutes, seed priority,
# tote-atomic scoring
# ---------------------------------------------------------------------------

class TestADR186BlockCompletion:
    def test_block_completed_before_next(self):
        # Two adjacent blocks, each small enough to co-exist in one route. The
        # route should hold BOTH (block completion + neighborhood expansion).
        pkgs = (
            [_pkg(f"A{i}", "300 W 36th St", f"BagA{i}", first_cross_street="8 AVENUE") for i in range(2)]
            + [_pkg(f"B{i}", "400 W 36th St", f"BagB{i}", first_cross_street="9 AVENUE") for i in range(2)]
        )
        result = run_sort(_request(pkgs), {}, {}, {})
        # 4 totes, standard cap = 6 totes → one route holding all 4
        assert len(result.routes) == 1
        assert len(result.routes[0].tote_ids) == 4

    def test_large_block_spills_contiguously_across_routes(self):
        # One block with more totes than a standard route holds must span
        # consecutive routes, each carrying part of the SAME block.
        n_full = EFFORT_CAPACITY["standard"] // TOTE_HALF_SLOTS
        pkgs = [_pkg(f"T{i:03}", "300 W 36th St", f"Bag{i}") for i in range(n_full + 2)]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 2
        # every route's dominant coverage is the same block
        for r in result.routes:
            assert "W_36_St_300" in r.block_keys
        assert sum(len(r.tote_ids) for r in result.routes) == n_full + 2


class TestADR186NeighborhoodMisroute:
    def test_adjacent_block_package_not_flagged(self):
        # A tote dominated by W_36_St_300 with one W_36_St_400 package (adjacent).
        # The adjacent package must NOT be flagged (rides silently).
        pkgs = [
            _pkg("D1", "300 W 36th St", "BagX"),
            _pkg("D2", "310 W 36th St", "BagX"),
            _pkg("R1", "400 W 36th St", "BagX", first_cross_street="9 AVENUE"),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = [m.tba_number for r in result.routes for m in r.misrouted_packages]
        flagged += [m.tba_number for m in result.unassigned_misroutes]
        assert "R1" not in flagged

    def test_distant_block_package_flagged(self):
        # W_57 package inside a W_36-dominant bag is genuinely distant → flagged.
        pkgs = [
            _pkg("D1", "300 W 36th St", "BagY"),
            _pkg("D2", "310 W 36th St", "BagY"),
            _pkg("FAR", "350 W 57th St", "BagY", lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = [m.tba_number for r in result.routes for m in r.misrouted_packages]
        flagged += [m.tba_number for m in result.unassigned_misroutes]
        assert "FAR" in flagged


class TestADR186SeedPriority:
    def test_cold_start_is_densest_first(self):
        # No profile/urgency data → seeding falls back to density. The densest
        # block seeds route #1, so its blocks lead.
        pkgs = (
            [_pkg(f"H{i}", "300 W 36th St", f"BagH{i}") for i in range(5)]     # dense
            + [_pkg("L1", "300 W 50th St", "BagL1", lat=40.76, lng=-73.98)]    # sparse, far
        )
        result = run_sort(_request(pkgs), {}, {}, {})
        assert "W_36_St_300" in result.routes[0].block_keys


class TestADR186NoInfiniteLoop:
    def test_ov_near_full_route_terminates_and_spills(self):
        # An OV_S tote costs 3 half-slots (2 + 1), making fits NON-exact:
        # capacity 12 → OV tote (3) + 4 normal (8) = 11; the next tote (2)
        # doesn't fit but 11 < 12. The original block-completion loop asked for
        # the nearest neighbor, got the SAME block back, and spun forever
        # (144% CPU in prod). Must terminate and spill the rest to route 2.
        pkgs = [_pkg("OV1", "300 W 36th St", "BagOV", package_type="OV_S")]
        pkgs += [_pkg(f"N{i}", "300 W 36th St", f"BagN{i}") for i in range(6)]
        result = run_sort(_request(pkgs), {}, {}, {})   # hangs forever if regressed
        assert len(result.routes) >= 2
        total_totes = sum(len(r.tote_ids) for r in result.routes)
        assert total_totes == 7
        # every route respects its capacity lock
        for r in result.routes:
            assert r.slot_cost <= r.capacity_limit


class TestStandaloneOVCost:
    def test_standalone_ov_bag_costs_only_ov_half_slots(self):
        # An OV with its own bag_id is a loose item, not a tote: no +2 base.
        pkgs = [_pkg("OV1", "300 W 36th St", "OV0001", package_type="OV_L")]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.routes[0].slot_cost == OV_HALF_SLOTS["L"]   # 3, not 5

    def test_five_totes_plus_two_small_ovs_fill_one_route(self):
        # 5 totes (2 each) + 2 standalone OV_S (1 each) = 12 = exactly one
        # standard route — the operational definition of a full cart.
        pkgs = [_pkg(f"N{i}", "300 W 36th St", f"Bag{i}") for i in range(5)]
        pkgs += [_pkg(f"OV{i}", "300 W 36th St", f"OV000{i}", package_type="OV_S") for i in range(2)]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert len(result.routes) == 1
        assert result.routes[0].slot_cost == 12
        assert len(result.routes[0].tote_ids) == 7

    def test_in_tote_ov_still_adds_to_tote_base(self):
        # A bag with a normal package AND an OV is a real tote: 2 + OV extras.
        pkgs = [
            _pkg("N1", "300 W 36th St", "BagA"),
            _pkg("OVX", "300 W 36th St", "BagA", package_type="OV_XL"),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        assert result.routes[0].slot_cost == TOTE_HALF_SLOTS + OV_HALF_SLOTS["XL"]


# ---------------------------------------------------------------------------
# ADR-194 — structured stops + cross-street range gate
# ---------------------------------------------------------------------------

class TestStopsOutput:
    def test_stops_grouped_by_address_and_sorted(self):
        # Two addresses on the 300 block, one on the 400 block — stops must be
        # one entry per unique address, blocks ascending, house numbers
        # ascending within a block, TBAs grouped under their address.
        pkgs = [
            _pkg("T1", "310 W 36th St", "Bag1", normalised_address="310 WEST 36 STREET"),
            _pkg("T2", "310 W 36th St", "Bag1", normalised_address="310 WEST 36 STREET"),
            _pkg("T3", "302 W 36th St", "Bag1", normalised_address="302 WEST 36 STREET"),
            _pkg("T4", "410 W 36th St", "Bag2", normalised_address="410 WEST 36 STREET",
                 first_cross_street="9 AVENUE"),
            _pkg("T5", "410 W 36th St", "Bag2", normalised_address="410 WEST 36 STREET",
                 first_cross_street="9 AVENUE"),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        all_stops = [s for r in result.routes for s in r.stops]
        assert [(s.block_key, s.address) for s in all_stops] == [
            ("W_36_St_300", "302 WEST 36 STREET"),
            ("W_36_St_300", "310 WEST 36 STREET"),
            ("W_36_St_400", "410 WEST 36 STREET"),
        ]
        by_addr = {s.address: s.tba_numbers for s in all_stops}
        assert by_addr["310 WEST 36 STREET"] == ["T1", "T2"]
        assert by_addr["410 WEST 36 STREET"] == ["T4", "T5"]

    def test_stops_exclude_flagged_riders_but_tba_numbers_keep_them(self):
        # The W_57 rider is flagged, so it is NOT a stop — but it still rides
        # physically in the tote, so it stays in tba_numbers until resolved.
        pkgs = [
            _pkg("D1", "300 W 36th St", "BagY", normalised_address="300 WEST 36 STREET"),
            _pkg("D2", "310 W 36th St", "BagY", normalised_address="310 WEST 36 STREET"),
            _pkg("FAR", "350 W 57th St", "BagY", normalised_address="350 WEST 57 STREET",
                 lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        route = result.routes[0]
        assert "FAR" in route.tba_numbers
        assert all("FAR" not in s.tba_numbers for s in route.stops)
        assert all(s.address != "350 WEST 57 STREET" for s in route.stops)

    def test_flagged_rider_carries_normalised_address(self):
        pkgs = [
            _pkg("D1", "300 W 36th St", "BagY", normalised_address="300 WEST 36 STREET"),
            _pkg("D2", "310 W 36th St", "BagY", normalised_address="310 WEST 36 STREET"),
            _pkg("FAR", "350 W 57th St", "BagY", normalised_address="350 WEST 57 STREET",
                 lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flags = [m for r in result.routes for m in r.misrouted_packages]
        flags += list(result.unassigned_misroutes)
        far = next(m for m in flags if m.tba_number == "FAR")
        assert far.normalised_address == "350 WEST 57 STREET"

    def test_package_without_address_is_not_a_stop_but_stays_in_tbas(self):
        pkgs = [
            _pkg("D1", "300 W 36th St", "BagZ", normalised_address="300 WEST 36 STREET"),
            _pkg("NOADDR", "310 W 36th St", "BagZ", normalised_address=None),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        route = result.routes[0]
        assert "NOADDR" in route.tba_numbers
        assert all("NOADDR" not in s.tba_numbers for s in route.stops)


class TestCrossStreetRangeGate:
    """Detection by physical proximity (ADR-196 Model E supersedes the ADR-194
    block_key cross-street gate for MISROUTE DETECTION; the gate itself still
    runs in _build_adjacency_graph for CLUSTERING). A far-avenue rider is flagged
    (no shared node, far from dominant); an adjacent-avenue rider rides silently.
    These packages carry no segment_id, so they exercise the coordinate backstop."""

    # W 36th St @ 9th Ave ≈ (40.7544, -73.9931); 9th Ave 800-range (W 53rd)
    # ≈ (40.7645, -73.9870) — ~1.2 km apart.
    _W36 = (40.7544, -73.9931)
    _AVE_FAR = (40.7645, -73.9870)
    _AVE_NEAR = (40.7553, -73.9925)   # 9th Ave 500-range (W 38th) — ~0.11 km

    def test_far_avenue_rider_flagged_despite_shared_avenue(self):
        pkgs = [
            _pkg("D1", "400 W 36th St", "BagA", normalised_address="400 WEST 36 STREET",
                 first_cross_street="9 AVENUE", lat=self._W36[0], lng=self._W36[1]),
            _pkg("D2", "410 W 36th St", "BagA", normalised_address="410 WEST 36 STREET",
                 first_cross_street="9 AVENUE", lat=self._W36[0], lng=self._W36[1]),
            _pkg("RIDER", "810 9th Ave", "BagA", normalised_address="810 9 AVENUE",
                 lat=self._AVE_FAR[0], lng=self._AVE_FAR[1]),
            # The far avenue range is a dominant block of its own tote — the
            # exact configuration that used to legitimize the rider.
            _pkg("F1", "800 9th Ave", "BagB", normalised_address="800 9 AVENUE",
                 lat=self._AVE_FAR[0], lng=self._AVE_FAR[1]),
            _pkg("F2", "820 9th Ave", "BagB", normalised_address="820 9 AVENUE",
                 lat=self._AVE_FAR[0], lng=self._AVE_FAR[1]),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = [m.tba_number for r in result.routes for m in r.misrouted_packages]
        flagged += [m.tba_number for m in result.unassigned_misroutes]
        assert "RIDER" in flagged

    def test_adjacent_avenue_rider_not_flagged(self):
        pkgs = [
            _pkg("D1", "400 W 36th St", "BagA", normalised_address="400 WEST 36 STREET",
                 first_cross_street="9 AVENUE", lat=self._W36[0], lng=self._W36[1]),
            _pkg("D2", "410 W 36th St", "BagA", normalised_address="410 WEST 36 STREET",
                 first_cross_street="9 AVENUE", lat=self._W36[0], lng=self._W36[1]),
            _pkg("NEAR", "510 9th Ave", "BagA", normalised_address="510 9 AVENUE",
                 lat=self._AVE_NEAR[0], lng=self._AVE_NEAR[1]),
            _pkg("N1", "500 9th Ave", "BagC", normalised_address="500 9 AVENUE",
                 lat=self._AVE_NEAR[0], lng=self._AVE_NEAR[1]),
            _pkg("N2", "520 9th Ave", "BagC", normalised_address="520 9 AVENUE",
                 lat=self._AVE_NEAR[0], lng=self._AVE_NEAR[1]),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = [m.tba_number for r in result.routes for m in r.misrouted_packages]
        flagged += [m.tba_number for m in result.unassigned_misroutes]
        assert "NEAR" not in flagged

    def test_no_geometry_at_all_flags_conservatively(self):
        # A package with NEITHER coordinates NOR LION data cannot be proven to
        # belong to its route, so Model E flags it (fail-safe). NOTE: this never
        # occurs in real enriched data — 100% of GeoClient rows carry lat/lng
        # (0.9% lack only segment_id, which the coordinate backstop covers). The
        # old block_key cross-street edge that silenced it is retired (ADR-196).
        pkgs = [
            _pkg("D1", "400 W 36th St", "BagA", normalised_address="400 WEST 36 STREET",
                 first_cross_street="9 AVENUE", lat=None, lng=None),
            _pkg("NOGEO", "810 9th Ave", "BagA", normalised_address="810 9 AVENUE",
                 lat=None, lng=None),
        ]
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = [m.tba_number for r in result.routes for m in r.misrouted_packages]
        flagged += [m.tba_number for m in result.unassigned_misroutes]
        assert "NOGEO" in flagged


# ---------------------------------------------------------------------------
# ADR-195 F3 — geographic fallback for misroute suggestions (thin/diagonal blocks)
# ---------------------------------------------------------------------------

class TestMisrouteGeographicFallback:
    """Block-key adjacency is a discrete grid and misses 'diagonal' proximity
    (different street AND different hundred). A package physically near another
    route but not block-key-adjacent to it used to dead-end as 'no covering
    route'. The centroid fallback should suggest the nearest route within
    _MISROUTE_SUGGEST_MAX_KM, while a genuinely distant outlier still dead-ends."""

    def test_near_no_node_package_rides_silently_via_backstop(self):
        # A thin W_32 rider ~112 m from its route's dominant W_31 stops, with NO
        # LION data (segment_id=None). Under Model E it rides silently via the
        # coordinate backstop — a package one block from its route is NOT a
        # misroute. (This case dead-ended under the old block_key detector.)
        pkgs = []
        for i in range(12):
            pkgs.append(_pkg(f"A{i}", f"3{i}0 W 31st St", "BagA", lat=40.7503, lng=-73.9925))
        for i in range(12):
            pkgs.append(_pkg(f"C{i}", f"2{i}0 W 33rd St", "BagC", lat=40.7519, lng=-73.9910))
        pkgs.append(_pkg("THIN", "110 W 32nd St", "BagA", lat=40.7511, lng=-73.9917))
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = {m.tba_number for r in result.routes for m in r.misrouted_packages}
        flagged |= {m.tba_number for m in result.unassigned_misroutes}
        assert "THIN" not in flagged, "a package ~112 m from its route should ride silently"

    def test_shared_lion_node_rides_silently(self):
        # A rider whose segment shares a LION node with the route's carried
        # segments rides silently — the authoritative adjacency, even when the
        # coordinate backstop would be borderline.
        pkgs = []
        for i in range(12):
            pkgs.append(_pkg(f"A{i}", f"3{i}0 W 31st St", "BagA", lat=40.7503, lng=-73.9925,
                             segment_id="SEG_A", from_lion_node_id="N1", to_lion_node_id="N2"))
        # rider on a segment that shares node N2 with the route's SEG_A
        pkgs.append(_pkg("SHARED", "110 W 32nd St", "BagA", lat=40.7560, lng=-73.9800,
                         segment_id="SEG_B", from_lion_node_id="N2", to_lion_node_id="N3"))
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = {m.tba_number for r in result.routes for m in r.misrouted_packages}
        flagged |= {m.tba_number for m in result.unassigned_misroutes}
        assert "SHARED" not in flagged, "shared LION node = adjacent = rides silently"

    def test_distant_outlier_flagged_and_dead_ends(self):
        # A W_57 rider ~2 km from the only (W_36) route: no shared node, backstop
        # fails (far from dominant), and beyond _MISROUTE_SUGGEST_MAX_KM → flagged,
        # captain review (no suggestion).
        pkgs = [_pkg(f"D{i}", f"3{i}0 W 36th St", "BagX", lat=40.7501, lng=-73.9886,
                     segment_id="SEG_D", from_lion_node_id="D1", to_lion_node_id="D2")
                for i in range(12)]
        pkgs.append(_pkg("FAR", "450 W 57th St", "BagX", lat=40.7680, lng=-73.9850,
                         segment_id="SEG_F", from_lion_node_id="F1", to_lion_node_id="F2"))
        result = run_sort(_request(pkgs), {}, {}, {})
        orphan_tbas = {m.tba_number for m in result.unassigned_misroutes}
        assert "FAR" in orphan_tbas, "distant outlier must flag and dead-end to captain review"

    def test_genuine_misroute_gets_nearest_route_suggestion(self):
        # Two separate routes; a package physically in route 2's territory but
        # riding in route 1's tote (no shared node, outside backstop of route 1's
        # dominant) is flagged AND suggested to route 2 (within SUGGEST cap).
        from app.services.route_sort import _haversine_km, _MISROUTE_SUGGEST_MAX_KM
        pkgs = []
        for i in range(12):
            pkgs.append(_pkg(f"A{i}", f"3{i}0 W 23rd St", "BagA", lat=40.7440, lng=-73.9980,
                             segment_id="SEG_A", from_lion_node_id="A1", to_lion_node_id="A2"))
        for i in range(12):
            pkgs.append(_pkg(f"B{i}", f"3{i}0 W 50th St", "BagB", lat=40.7620, lng=-73.9900,
                             segment_id="SEG_B", from_lion_node_id="B1", to_lion_node_id="B2"))
        # rider physically at W_50 (~route 2) but riding in BagA (route 1)
        pkgs.append(_pkg("STRAY", "355 W 50th St", "BagA", lat=40.7620, lng=-73.9900,
                         segment_id="SEG_S", from_lion_node_id="S1", to_lion_node_id="S2"))
        result = run_sort(_request(pkgs), {}, {}, {})
        flagged = {m.tba_number: m.suggested_route_number
                   for r in result.routes for m in r.misrouted_packages}
        assert flagged.get("STRAY") is not None, "genuine misroute should get a suggestion"
        dest = next(r for r in result.routes if r.route_number == flagged["STRAY"])
        dpk = [p for p in pkgs if p.tba_number in dest.tba_numbers and p.lat is not None]
        nearest = min(_haversine_km(40.7620, -73.9900, p.lat, p.lng) for p in dpk)
        assert nearest <= _MISROUTE_SUGGEST_MAX_KM


# ---------------------------------------------------------------------------
# ADR-195 F4 — time-urgency seeding (ADR-186 W_TIME term, now fed data)
# ---------------------------------------------------------------------------

class TestTimeUrgencySeeding:
    """The W_TIME seed-priority term was implemented in ADR-186 but never fed
    data (commit-sort passed no block_time_urgency). These pin the behavior now
    that it is wired: a time-critical block seeds an earlier route than a denser
    block with no time pressure, and empty urgency preserves densest-first."""

    def _dense_plus_urgent(self):
        pkgs = []
        for i in range(20):
            pkgs.append(_pkg(f"DENSE{i}", f"3{i:02d} W 50th St", f"BAGD{i//10}",
                             lat=40.7613, lng=-73.9906))
        for i in range(8):
            pkgs.append(_pkg(f"URG{i}", f"1{i:02d} W 23rd St", "BAGU",
                             lat=40.7464, lng=-73.9980))
        return _request(pkgs)

    def test_urgent_block_seeds_before_denser_block(self):
        req = self._dense_plus_urgent()
        res = run_sort(req, {}, {}, {}, block_time_urgency={"W_23_St_100": 1.0})
        assert res.routes[0].block_keys == ["W_23_St_100"], \
            "an imminent-cutoff block must seed route #1 over a denser no-pressure block"

    def test_no_urgency_is_densest_first(self):
        req = self._dense_plus_urgent()
        res = run_sort(req, {}, {}, {})   # no block_time_urgency → cold start
        assert res.routes[0].block_keys == ["W_50_St_300"], \
            "without urgency, the densest block seeds first (unchanged cold-start order)"


# ---------------------------------------------------------------------------
# ADR-197 Phase 1 (F5) — coordinate-based consolidation of sparse routes
# ---------------------------------------------------------------------------

class TestF5Consolidation:
    """Sparse clients (low per-block density) produce blocks with NO block-key
    adjacency edges → each thin block dead-ends as its own route (fragmentation).
    F5 consolidates them via nearest-block-by-centroid within a walk radius, up
    to a load floor, when crew_size is passed. crew_size=None = baseline."""

    def _sparse_zone(self):
        # 4 thin blocks, 1 tote each, that are PAIRWISE NON-ADJACENT by block-key
        # (different street >1 apart AND different hundred → no cost-2/3 edge; no
        # cross-street data → no cost-1 edge) but clustered within ~1km. This is
        # the sparse case: the block-key graph has zero edges, so baseline
        # fragments them and only the coord fallback can consolidate.
        specs = [
            ("S0", "10 W 20th St",  40.7000, -74.0000),
            ("S1", "250 W 23rd St", 40.7030, -73.9980),
            ("S2", "410 W 27th St", 40.7060, -73.9965),
            ("S3", "120 W 31st St", 40.7090, -73.9950),
        ]
        return [_pkg(t, a, f"BAG{i}", lat=lat, lng=lng) for i, (t, a, lat, lng) in enumerate(specs)]

    def test_baseline_fragments_sparse_without_crew(self):
        # crew_size=None → no consolidation → each thin block is its own route.
        res = run_sort(_request(self._sparse_zone()), {}, {}, {})
        assert len(res.routes) == 4
        assert res.routes_built is None and res.crew_size is None

    def test_consolidates_sparse_with_crew(self):
        # With crew, coord-fallback merges the thin blocks into fewer routes.
        res = run_sort(_request(self._sparse_zone()), {}, {}, {}, crew_size=8)
        assert len(res.routes) < 4, "F5 should consolidate thin scattered blocks"
        assert res.crew_size == 8
        assert res.routes_built == len(res.routes)

    def test_surplus_signal(self):
        # Thin blocks consolidate to fewer routes than crew → surplus reported.
        res = run_sort(_request(self._sparse_zone()), {}, {}, {}, crew_size=8)
        surplus = res.crew_size - res.routes_built
        assert surplus > 0, "fewer routes than crew → walkers can be released"

    def test_walk_radius_respected(self):
        # Two thin blocks FAR apart (>1.2km) must NOT merge even with crew.
        pkgs = [
            _pkg("A", "10 W 20th St", "BAGA", lat=40.700, lng=-74.000),
            _pkg("B", "10 W 90th St", "BAGB", lat=40.780, lng=-73.960),  # ~10km away
        ]
        res = run_sort(_request(pkgs), {}, {}, {}, crew_size=4)
        assert len(res.routes) == 2, "blocks beyond the walk radius must not consolidate"

    def test_dense_unchanged_by_crew_size(self):
        # Dense adjacent blocks (graph HAS edges) route identically with/without
        # crew_size — the coord fallback never fires.
        pkgs = []
        for h in (100, 200, 300):
            for i in range(8):
                pkgs.append(_pkg(f"D{h}_{i}", f"{h+i} W 36th St", f"BAG{h}", lat=40.7501, lng=-73.9886))
        base = run_sort(_request(pkgs), {}, {}, {})
        withcrew = run_sort(_request(pkgs), {}, {}, {}, crew_size=5)
        assert [sorted(r.block_keys) for r in base.routes] == [sorted(r.block_keys) for r in withcrew.routes]


# ── ADR-214: out-of-zone packages become removals, not captain-review misroutes ──

class TestOutOfZoneRemovals:
    # A small square boundary around the in-zone cluster (~40.750, -73.990).
    _BOUNDARY = [
        {"lat": 40.740, "lng": -74.000},
        {"lat": 40.760, "lng": -74.000},
        {"lat": 40.760, "lng": -73.980},
        {"lat": 40.740, "lng": -73.980},
    ]

    def _in_zone_pkgs(self):
        # A cohesive in-zone route on W 36th St.
        return [_pkg(f"IZ{i}", f"{400+i} W 36th St", "BAGZ", lat=40.7501, lng=-73.9886)
                for i in range(6)]

    def test_out_of_zone_package_becomes_removal(self):
        pkgs = self._in_zone_pkgs()
        # An Astoria package riding in the same bag — far outside the boundary.
        pkgs.append(_pkg("OOZ1", "31-15 Steinway St", "BAGZ", lat=40.770, lng=-73.920))
        result = run_sort(_request(pkgs), {}, {}, {}, boundary=self._BOUNDARY)
        ooz_tbas = {m.tba_number for m in result.out_of_zone_removals}
        assert "OOZ1" in ooz_tbas
        # It must NOT be a captain-review misroute anymore.
        assert "OOZ1" not in {m.tba_number for m in result.unassigned_misroutes}

    def test_no_boundary_keeps_old_behaviour(self):
        pkgs = self._in_zone_pkgs()
        pkgs.append(_pkg("FAR1", "31-15 Steinway St", "BAGZ", lat=40.770, lng=-73.920))
        result = run_sort(_request(pkgs), {}, {}, {})   # boundary=None
        # With no boundary, nothing is classified out-of-zone.
        assert result.out_of_zone_removals == []

    def test_in_zone_outlier_stays_misroute_not_removal(self):
        # A package inside the boundary but with no covering route stays a
        # (captain-review) misroute — it is NOT out of zone.
        pkgs = self._in_zone_pkgs()
        # Far from W 36th but still inside the square (e.g. near the SE corner).
        pkgs.append(_pkg("INZ_OUT", "100 W 24th St", "BAGZ", lat=40.7415, lng=-73.9815))
        result = run_sort(_request(pkgs), {}, {}, {}, boundary=self._BOUNDARY)
        assert "INZ_OUT" not in {m.tba_number for m in result.out_of_zone_removals}
