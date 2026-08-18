"""A hub has a loading stage (ADR-274 D12).

THE GAP
-------
Every endpoint in the loading chain resolved its work through `_active_zones`
and 404'd when there was none:

    rosters / check / check-all / confirm-load / unconfirm-load

A hub has no TruckZone by design (D2), so a hub driver could not check off a
tote and — worse — could not tell dispatch the truck was loaded. ADR-181's
driver->dispatch handoff had a permanent hole, and dispatch had no ready signal.

THE FIX
-------
A roster is not really a product of the sort: it is a pure function of manifest
packages (group by bag_id, count, read the dock tag). The builder moved out of
`persist_zones` into `services/tote_roster.py`, and the hub builds the identical
roster from its own Redis manifest.

The behavioural tests below run the REAL builder over real package dicts. The
structural ones guard the properties a source change would silently break —
chiefly that there is still only ONE roster implementation.
"""
from pathlib import Path

import pytest

try:
    from app.services.tote_roster import build_tote_roster, roster_inputs_from_packages
except ImportError:  # pragma: no cover
    # tote_roster is gitignored proprietary (ADR-274 D12) — absent in the public
    # checkout, where an unguarded import crashes COLLECTION and takes the whole
    # suite with it, not just this module.
    pytest.skip("proprietary sort services not available (CI skip)", allow_module_level=True)


BACKEND = Path(__file__).resolve().parents[2]
SORT_ROUTER = BACKEND / "app" / "routers" / "sort.py"
PERSIST = BACKEND / "app" / "services" / "persist_zones.py"


def _pkg(tba, bag=None, tag=None, ptype=None, block=None):
    return {
        "tba": tba, "bag_id": bag, "tag_number": tag,
        "package_type": ptype, "block_key": block,
    }


class TestRosterFromManifest:
    """The behaviour a hub driver actually gets."""

    def test_packages_group_into_totes_by_bag(self):
        pkgs = [
            _pkg("T1", "BAG_A", "A3", block="BK1"),
            _pkg("T2", "BAG_A", "A3", block="BK1"),
            _pkg("T3", "BAG_B", "B1", block="BK2"),
        ]
        tba_bag, info = roster_inputs_from_packages(pkgs)
        roster = build_tote_roster([p["tba"] for p in pkgs], tba_bag, info)

        assert {r["bag_id"] for r in roster} == {"BAG_A", "BAG_B"}
        by_bag = {r["bag_id"]: r for r in roster}
        assert by_bag["BAG_A"]["package_count"] == 2
        assert by_bag["BAG_B"]["package_count"] == 1

    def test_unbagged_package_becomes_its_own_tote(self):
        # A walker holding an unbagged package must still find it on the sheet.
        # Silently dropping it is the failure mode this guards.
        pkgs = [_pkg("T1", "BAG_A"), _pkg("T2", None)]
        tba_bag, info = roster_inputs_from_packages(pkgs)
        roster = build_tote_roster([p["tba"] for p in pkgs], tba_bag, info)

        assert len(roster) == 2, "the bagless package vanished from the roster"
        assert any(r["bag_id"] == "(loose) T2" for r in roster)
        assert sum(r["package_count"] for r in roster) == 2

    def test_every_tba_appears_exactly_once(self):
        # The roster IS the check-off list. A duplicate makes a tote impossible
        # to fully check; a drop makes the truck silently short.
        pkgs = [_pkg(f"T{i}", f"BAG_{i % 3}") for i in range(12)] + [_pkg("LOOSE", None)]
        tba_bag, info = roster_inputs_from_packages(pkgs)
        roster = build_tote_roster([p["tba"] for p in pkgs], tba_bag, info)

        seen = [t for r in roster for t in r["tba_numbers"]]
        assert sorted(seen) == sorted(p["tba"] for p in pkgs)
        assert len(seen) == len(set(seen)), "a TBA appears in two totes"

    def test_ov_packages_are_counted_separately(self):
        pkgs = [
            _pkg("T1", "BAG_A", "A3", ptype="OV_L"),
            _pkg("T2", "BAG_A", "A3", ptype="standard"),
        ]
        tba_bag, info = roster_inputs_from_packages(pkgs)
        roster = build_tote_roster(["T1", "T2"], tba_bag, info)
        assert roster[0]["ov_count"] == 1
        assert roster[0]["ov_sizes"] == ["OV_L"]

    def test_riders_counted_against_the_dominant_block(self):
        pkgs = [
            _pkg("T1", "BAG_A", block="BK1"),
            _pkg("T2", "BAG_A", block="BK1"),
            _pkg("T3", "BAG_A", block="BK9"),   # the rider
        ]
        tba_bag, info = roster_inputs_from_packages(pkgs)
        roster = build_tote_roster(["T1", "T2", "T3"], tba_bag, info)
        assert roster[0]["rider_count"] == 1

    def test_empty_manifest_yields_empty_roster_not_an_error(self):
        assert build_tote_roster([], {}, {}) == []

    def test_packages_without_a_tba_are_skipped_not_crashed(self):
        # Enrichment can emit a row with no tba; it must not take the dock down.
        tba_bag, info = roster_inputs_from_packages([{"bag_id": "BAG_A"}, _pkg("T1", "BAG_A")])
        roster = build_tote_roster(["T1"], tba_bag, info)
        assert roster[0]["package_count"] == 1


class TestOneImplementation:
    """The extraction must not become a copy (the reason it was extracted)."""

    @pytest.mark.skipif(not PERSIST.exists(), reason="persist_zones is proprietary")
    def test_persist_zones_delegates_rather_than_duplicates(self):
        src = PERSIST.read_text(encoding="utf-8")
        assert "from app.services.tote_roster import build_tote_roster" in src
        assert "return build_tote_roster(tbas, tba_bag, pkg_info)" in src, (
            "persist_zones no longer delegates — two roster implementations "
            "will drift, and check-off would mean different things on a hub "
            "than on a regular truck"
        )

    def test_the_roster_body_lives_in_exactly_one_place(self):
        # The dock-tag ordering is the subtlest line; if it appears in two
        # files, the copies have already begun.
        needle = 'roster.sort(key=lambda r: (r["dock_tags"][0] if r["dock_tags"] else "~", r["bag_id"]))'
        hits = [
            p.name for p in (BACKEND / "app").rglob("*.py")
            if "__pycache__" not in p.parts and needle in p.read_text(encoding="utf-8")
        ]
        assert hits == ["tote_roster.py"], f"roster body duplicated into: {hits}"


class TestLoadingEndpointsReachHubs:
    """Structural: the four endpoints no longer hard-gate on a TruckZone."""

    @pytest.fixture(scope="class")
    def src(self) -> str:
        return SORT_ROUTER.read_text(encoding="utf-8")

    def test_no_endpoint_still_filters_active_zones_inline(self, src: str):
        # This exact line is what excluded hubs from all three endpoints.
        stale = "zones = [z for z in _active_zones(db, caller.company_id, sort_date) if z.truck_id == truck_id]"
        assert stale not in src, (
            "an endpoint still resolves zones inline instead of via "
            "_zones_for_truck, so it 404s for a hub"
        )

    def test_all_three_use_the_shared_resolver(self, src: str):
        assert src.count("_zones_for_truck(db, caller.company_id, sort_date, truck_id)") == 3, (
            "expected check-all, confirm-load and unconfirm-load to share the "
            "hub-aware resolver"
        )

    def test_check_tote_falls_back_to_hub_rosters(self, src: str):
        i = src.index("def check_tote(")
        body = src[i:src.index("\n@router.", i)]
        assert "_hub_rosters(" in body, "check_tote cannot find a hub's tote"
        assert "home_truck_id" in body, (
            "check_tote still derives the truck from a zone object a hub lacks"
        )

    def test_hub_rosters_is_company_and_date_scoped(self, src: str):
        i = src.index("def _hub_rosters(")
        body = src[i:src.index("\ndef ", i + 10)]
        assert "Truck.company_id == company_id" in body
        assert "TruckAssignment.company_id == company_id" in body
        assert "TruckAssignment.date == sort_date" in body
        assert "_manifest_key(cid," in body, "manifest key is not company-scoped"
        assert "#hub:" in body, "manifest key is not namespaced per hub"

    def test_corrupt_hub_manifest_does_not_break_the_dock(self, src: str):
        i = src.index("def _hub_rosters(")
        body = src[i:src.index("\ndef ", i + 10)]
        assert "except (json.JSONDecodeError, TypeError)" in body, (
            "one corrupt hub manifest would 500 the roster for every truck"
        )

    def test_only_assigned_hubs_appear(self, src: str):
        i = src.index("def _hub_rosters(")
        body = src[i:src.index("\ndef ", i + 10)]
        assert "if not assigned:" in body, (
            "a hub truck with no assignment today is not 'unloaded' — it is "
            "not running, and must not appear on the dock"
        )


class TestGatesStayIndependent:
    """Commit-sort must NOT wait on the hub's load confirmation (operator call)."""

    def test_zone_status_does_not_consult_load_confirmation(self):
        src = SORT_ROUTER.read_text(encoding="utf-8")
        i = src.index("def get_zone_status(")
        body = src[i:src.index("\n@router.", i)]
        assert "LoadConfirmation" not in body, (
            "the commit gate now depends on load confirmation; the two signals "
            "were deliberately kept independent for hubs (D12)"
        )
