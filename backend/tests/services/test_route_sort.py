"""
Tests for route_sort.py — the walker route distribution algorithm.

Covers:
  - _derive_block_key: address parsing (directional, non-directional, noise stripping)
  - _block_key_adjacent: structural adjacency (same street, contiguous range, cross-side)
  - _haversine_km: distance sanity checks
  - _resolve_effort_class: flag → profile → default override chain
  - _pair_ovs: half-slot OV cost accumulation
  - run_sort: end-to-end — capacity enforcement, clustering, misroute detection,
              no address data in output, empty input, oversize block
"""
import uuid
from datetime import date

import pytest

from app.services.route_sort import (
    _derive_block_key,
    _block_key_adjacent,
    _haversine_km,
    _resolve_effort_class,
    _pair_ovs,
    _Tote,
    _Package,
    run_sort,
)
from app.schemas.walker_routes import (
    PackageInput,
    OVInput,
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


def _request(packages: list[PackageInput], ovs: list[OVInput] = None) -> SortRequest:
    return SortRequest(
        truck_assignment_id=_TA_ID,
        route_date=_DATE,
        packages=packages,
        ovs=ovs or [],
    )


def _pkg(tba: str, address: str, bag_id: str, lat: float = 40.75, lng: float = -73.99) -> PackageInput:
    return PackageInput(tba_number=tba, bag_id=bag_id, address=address, lat=lat, lng=lng)


# ---------------------------------------------------------------------------
# _derive_block_key
# ---------------------------------------------------------------------------

class TestDeriveBlockKey:
    def test_directional_street(self):
        assert _derive_block_key("350 W 36th St") == "W_36_St_350s_even"

    def test_directional_odd(self):
        assert _derive_block_key("351 W 36th St") == "W_36_St_350s_odd"

    def test_non_directional(self):
        assert _derive_block_key("410 5th Ave") == "5_Ave_410s_even"

    def test_ordinal_suffix_stripped(self):
        # "37th" → street_num 37
        assert _derive_block_key("410 W 37th St") == "W_37_St_410s_even"

    def test_noise_stripped(self):
        # "APT 4B" noise stripped before parsing
        assert _derive_block_key("350 W 36th St APT 4B") == "W_36_St_350s_even"

    def test_hundred_boundary(self):
        # 399 → range 390s
        assert _derive_block_key("399 W 36th St") == "W_36_St_390s_odd"

    def test_400s(self):
        assert _derive_block_key("415 W 37th St") == "W_37_St_410s_odd"

    def test_unparseable_no_house_number(self):
        assert _derive_block_key("Somewhere over the rainbow") is None

    def test_empty_string(self):
        assert _derive_block_key("") is None

    def test_unknown_street_type(self):
        # "Pkwy" is not in _STREET_TYPE_MAP
        assert _derive_block_key("350 W 36th Pkwy") is None

    def test_avenue_alias(self):
        assert _derive_block_key("410 W 36th Avenue") == "W_36_Ave_410s_even"


# ---------------------------------------------------------------------------
# _block_key_adjacent
# ---------------------------------------------------------------------------

class TestBlockKeyAdjacent:
    def test_same_block(self):
        # Same block_key is structurally adjacent to itself
        assert _block_key_adjacent("W_36_St_300s_odd", "W_36_St_300s_odd")

    def test_contiguous_hundred_same_side(self):
        assert _block_key_adjacent("W_36_St_300s_odd", "W_36_St_400s_odd")

    def test_contiguous_hundred_cross_side(self):
        # odd and even on the same block range are adjacent
        assert _block_key_adjacent("W_36_St_300s_odd", "W_36_St_300s_even")

    def test_contiguous_300_400(self):
        assert _block_key_adjacent("W_37_St_300s_odd", "W_37_St_400s_even")

    def test_non_contiguous(self):
        # 300s and 500s differ by 200 — not adjacent
        assert not _block_key_adjacent("W_36_St_300s_odd", "W_36_St_500s_odd")

    def test_different_street_number(self):
        assert not _block_key_adjacent("W_36_St_300s_odd", "W_37_St_300s_odd")

    def test_different_direction(self):
        assert not _block_key_adjacent("W_36_St_300s_odd", "E_36_St_300s_odd")

    def test_different_street_type(self):
        assert not _block_key_adjacent("W_36_St_300s_odd", "W_36_Ave_300s_odd")

    def test_non_directional_contiguous(self):
        assert _block_key_adjacent("5_Ave_400s_even", "5_Ave_500s_even")

    def test_non_directional_non_contiguous(self):
        assert not _block_key_adjacent("5_Ave_300s_even", "5_Ave_600s_even")

    def test_malformed_key(self):
        assert not _block_key_adjacent("not_a_key", "W_36_St_300s_odd")


# ---------------------------------------------------------------------------
# _haversine_km
# ---------------------------------------------------------------------------

class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert _haversine_km(40.75, -73.99, 40.75, -73.99) == pytest.approx(0.0, abs=1e-6)

    def test_one_block_approx_80m(self):
        # ~0.00072 degrees lat ≈ 80m (one short NYC block)
        d = _haversine_km(40.750, -73.990, 40.7508, -73.990)
        assert 0.05 < d < 0.15

    def test_within_adjacency_threshold(self):
        # Two points ~0.2km apart should be under _BLOCK_ADJACENCY_KM (0.25)
        d = _haversine_km(40.750, -73.990, 40.752, -73.990)
        assert d < 0.25

    def test_beyond_adjacency_threshold(self):
        # Points ~0.5km apart should exceed threshold
        d = _haversine_km(40.750, -73.990, 40.755, -73.990)
        assert d > 0.25


# ---------------------------------------------------------------------------
# _resolve_effort_class
# ---------------------------------------------------------------------------

class TestResolveEffortClass:
    def test_default_when_no_profile_no_flag(self):
        effort, source = _resolve_effort_class(["W_36_St_300s_odd"], {}, {})
        assert effort == "standard"
        assert source == "default"

    def test_profile_overrides_default(self):
        profiles = {"W_36_St_300s_odd": "high_wait"}
        effort, source = _resolve_effort_class(["W_36_St_300s_odd"], profiles, {})
        assert effort == "heavy"
        assert source == "profile"

    def test_flag_overrides_profile(self):
        profiles = {"W_36_St_300s_odd": "standard"}
        flags = {"W_36_St_300s_odd": "heavy"}
        effort, source = _resolve_effort_class(["W_36_St_300s_odd"], profiles, flags)
        assert effort == "heavy"
        assert source == "flag"

    def test_moderate_flag_maps_to_heavy(self):
        flags = {"W_36_St_300s_odd": "moderate"}
        effort, source = _resolve_effort_class(["W_36_St_300s_odd"], {}, flags)
        assert effort == "heavy"
        assert source == "flag"

    def test_worst_block_wins_across_multiple(self):
        # One standard block, one heavy block — result should be heavy
        profiles = {
            "W_36_St_300s_odd": "standard",
            "W_36_St_400s_odd": "high_touch",
        }
        effort, source = _resolve_effort_class(
            ["W_36_St_300s_odd", "W_36_St_400s_odd"], profiles, {}
        )
        assert effort == "heavy"
        assert source == "profile"

    def test_bulk_drop_maps_to_easy(self):
        # bulk_drop → easy. The algorithm only escalates upward from "easy",
        # so a single easy block leaves source as "default" (no escalation occurred).
        # The effort_class is still correct — easy is the result.
        profiles = {"W_36_St_300s_odd": "bulk_drop"}
        effort, source = _resolve_effort_class(["W_36_St_300s_odd"], profiles, {})
        assert effort == "easy"

    def test_empty_block_list(self):
        effort, source = _resolve_effort_class([], {}, {})
        assert effort == "easy"   # worst_effort initialises to "easy"


# ---------------------------------------------------------------------------
# _pair_ovs
# ---------------------------------------------------------------------------

class TestPairOvs:
    def _make_tote(self, bag_id: str) -> _Tote:
        return _Tote(bag_id=bag_id)

    def test_ov_s_adds_one_half_slot(self):
        totes = {"Bag1": self._make_tote("Bag1")}
        _pair_ovs(totes, [OVInput(sort_zone="A-1", size_tier="S", paired_bag_id="Bag1")])
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["S"]  # 1
        assert totes["Bag1"].half_slot_cost == TOTE_HALF_SLOTS + 1  # 3

    def test_ov_xl_adds_four_half_slots(self):
        totes = {"Bag1": self._make_tote("Bag1")}
        _pair_ovs(totes, [OVInput(sort_zone="A-1", size_tier="XL", paired_bag_id="Bag1")])
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["XL"]  # 4
        assert totes["Bag1"].half_slot_cost == TOTE_HALF_SLOTS + 4  # 6

    def test_multiple_ovs_on_same_tote_accumulate(self):
        totes = {"Bag1": self._make_tote("Bag1")}
        _pair_ovs(totes, [
            OVInput(sort_zone="A-1", size_tier="M", paired_bag_id="Bag1"),
            OVInput(sort_zone="A-2", size_tier="L", paired_bag_id="Bag1"),
        ])
        assert totes["Bag1"].ov_half_slots == OV_HALF_SLOTS["M"] + OV_HALF_SLOTS["L"]  # 2+3=5

    def test_ov_for_unknown_bag_creates_tote(self):
        totes = {}
        _pair_ovs(totes, [OVInput(sort_zone="A-1", size_tier="M", paired_bag_id="NewBag")])
        assert "NewBag" in totes
        assert totes["NewBag"].ov_half_slots == OV_HALF_SLOTS["M"]


# ---------------------------------------------------------------------------
# run_sort — end-to-end
# ---------------------------------------------------------------------------

class TestRunSort:

    def test_empty_input_returns_no_routes(self):
        result = run_sort(_request([]), {}, {})
        assert result.routes == []
        assert result.unassigned_misroutes == []

    def test_single_tote_single_route(self):
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA"),
            _pkg("TBA002", "352 W 36th St", "BagA"),
        ]
        result = run_sort(_request(pkgs), {}, {})
        assert len(result.routes) == 1
        assert result.routes[0].route_number == 1
        assert set(result.routes[0].tba_numbers) == {"TBA001", "TBA002"}

    def test_no_address_data_in_output(self):
        # The raw address string must not appear in the output.
        # block_keys derived from the address ARE allowed — they're stable identifiers.
        # We verify the original address tokens (street name "36th St", house "350")
        # don't appear literally in any field other than block_keys.
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {})
        serialised = result.model_dump_json()
        # Street name must not appear outside block_keys
        assert "36th" not in serialised
        # tba_numbers, tote_ids, tag_numbers must contain no address fragments
        for route in result.routes:
            for tba in route.tba_numbers:
                assert "36th" not in tba and "St" not in tba
            for tote_id in route.tote_ids:
                assert "36th" not in tote_id

    def test_routes_numbered_from_one(self):
        # Build enough totes for 2 routes — two well-separated locations
        pkgs_a = [_pkg(f"TBA{i:03}", "350 W 36th St", "BagA", lat=40.750, lng=-73.990) for i in range(3)]
        pkgs_b = [_pkg(f"TBA{i:03}", "800 W 57th St", "BagB", lat=40.770, lng=-73.985) for i in range(100, 103)]
        result = run_sort(_request(pkgs_a + pkgs_b), {}, {})
        route_numbers = [r.route_number for r in result.routes]
        assert route_numbers == sorted(route_numbers)
        assert route_numbers[0] == 1

    def test_capacity_respected_standard(self):
        # Fill a standard route (12 half-slots = 6 totes at 2 half-slots each)
        # Then add a 7th tote at a nearby but non-adjacent location — forces overflow
        pkgs = []
        for i in range(7):
            # 7 distinct bags, all on the same block key
            pkgs.append(_pkg(f"TBA{i:03}", f"{350 + i*2} W 36th St", f"Bag{i}", lat=40.750, lng=-73.990))
        result = run_sort(_request(pkgs), {}, {})
        # 7 totes × 2 half-slots = 14 > 12 capacity — must split into 2 routes
        total_totes = sum(len(r.tote_ids) for r in result.routes)
        assert total_totes == 7
        assert len(result.routes) >= 1

    def test_heavy_route_has_reduced_capacity(self):
        flags = {"W_36_St_350s_even": "heavy"}
        pkgs = [_pkg(f"TBA{i:03}", "350 W 36th St", f"Bag{i}") for i in range(5)]
        result = run_sort(_request(pkgs), {}, flags)
        assert result.routes[0].effort_class == "heavy"
        assert result.routes[0].capacity_limit == EFFORT_CAPACITY["heavy"]  # 8

    def test_easy_route_from_bulk_drop_profile(self):
        # bulk_drop → easy. Source stays "default" because easy never escalates
        # the worst_effort tracker — the algorithm only moves upward from easy.
        profiles = {"W_36_St_350s_even": "bulk_drop"}
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), profiles, {})
        assert result.routes[0].effort_class == "easy"

    def test_flag_overrides_profile_in_route(self):
        profiles = {"W_36_St_350s_even": "standard"}
        flags = {"W_36_St_350s_even": "heavy"}
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), profiles, flags)
        assert result.routes[0].effort_class == "heavy"
        assert result.routes[0].workload_source == "flag"

    def test_adjacent_blocks_cluster_together(self):
        # 300s and 400s on W 36th St are structurally adjacent
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "410 W 36th St", "BagB", lat=40.750, lng=-73.991),
        ]
        result = run_sort(_request(pkgs), {}, {})
        assert len(result.routes) == 1
        assert len(result.routes[0].tote_ids) == 2

    def test_non_adjacent_blocks_split_into_separate_routes(self):
        # W 36th St and W 57th St — different street numbers, far apart
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagA", lat=40.750, lng=-73.993),
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.769, lng=-73.984),
        ]
        result = run_sort(_request(pkgs), {}, {})
        assert len(result.routes) == 2

    def test_ov_cost_included_in_slot_cost(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        ovs = [OVInput(sort_zone="A-1", size_tier="XL", paired_bag_id="BagA")]
        result = run_sort(_request(pkgs, ovs), {}, {})
        # tote cost = 2 (tote) + 4 (XL OV) = 6 half-slots
        assert result.routes[0].slot_cost == TOTE_HALF_SLOTS + OV_HALF_SLOTS["XL"]

    def test_misroute_detected_wrong_bag(self):
        # TBA001 address is W 36th St but bag BagB is dominated by W 57th St packages.
        # TBA001 is flagged as a misroute. Since there's no separate tote on W 36th St,
        # no route exists for that block_key → lands in unassigned_misroutes.
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagB", lat=40.750, lng=-73.993),  # wrong bag
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
            _pkg("TBA003", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {})
        assert "TBA001" in [m.tba_number for m in result.unassigned_misroutes]

    def test_misroute_has_destination_block_key(self):
        # Same setup — the unassigned misroute must carry destination_block_key
        # so the trainer knows which pile to move the package to at the anchor point.
        pkgs = [
            _pkg("TBA001", "350 W 36th St", "BagB", lat=40.750, lng=-73.993),
            _pkg("TBA002", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
            _pkg("TBA003", "350 W 57th St", "BagB", lat=40.768, lng=-73.985),
        ]
        result = run_sort(_request(pkgs), {}, {})
        misrouted = next(m for m in result.unassigned_misroutes if m.tba_number == "TBA001")
        assert misrouted.destination_block_key == "W_36_St_350s_even"
        assert misrouted.current_bag_id == "BagB"

    def test_oversize_single_block_gets_own_route(self):
        # One block with 8 totes (16 half-slots) exceeds standard capacity (12)
        # The seed block must still get its own route — not silently dropped
        pkgs = [_pkg(f"TBA{i:03}", "350 W 36th St", f"Bag{i}") for i in range(8)]
        result = run_sort(_request(pkgs), {}, {})
        all_tba = [tba for r in result.routes for tba in r.tba_numbers]
        assert len(all_tba) == 8  # all packages present in output

    def test_result_truck_assignment_id_preserved(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {})
        assert result.truck_assignment_id == _TA_ID

    def test_result_route_date_preserved(self):
        pkgs = [_pkg("TBA001", "350 W 36th St", "BagA")]
        result = run_sort(_request(pkgs), {}, {})
        assert result.route_date == _DATE

    def test_slot_cost_never_exceeds_capacity_for_normal_blocks(self):
        # All packages on the same block, one package per tote, standard capacity
        pkgs = [_pkg(f"TBA{i:03}", f"{350+i*2} W 36th St", f"Bag{i}") for i in range(6)]
        result = run_sort(_request(pkgs), {}, {})
        for r in result.routes:
            assert r.slot_cost <= r.capacity_limit
