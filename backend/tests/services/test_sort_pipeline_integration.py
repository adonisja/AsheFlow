"""
Integration tests — manifest injection through TruckZone creation to route creation.

Covers the full sort pipeline in one connected flow (ADR-169/177):

  assign_totes()               ← tote-level anchored balanced assignment
      → analyze_sort()           ← non-blocking action lists (no review gate)
      → persist_zones()          ← TruckZone rows written directly
      → (_persist_routes stub)   ← Route rows built from TruckZone.package_tbas

The tests bypass Redis and the Celery task. Packages are injected as plain dicts
(the same structure enrich_manifest.py writes to Redis). The DB is a MagicMock
so we avoid PostgreSQL JSONB/UUID column types that SQLite cannot compile.

Test cases:

  1. Happy path — two trucks, clean bags, zones written, TBAs split correctly
  2. Tier-1 clean pass — no misloaded bags, persist_zones called
  3. Tier-1 flagged bags — misloaded bag detected, persist_zones NOT called
  4. Tier-1 override — dispatch confirms override, zones written with moved TBAs
  5. Zone → commit-sort handoff — TBAs in a zone match what _persist_routes receives
  6. Outlier packages — not in any cluster, surfaced as unresolvable in tier-1 result
  7. All-outlier bag — unresolvable=True because all outside TBAs are outliers
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

# Proprietary services are only present locally and on EC2 (injected at deploy time).
# The public repo ships the old tier1_verify without BagOverride — skip the entire
# module at collection time if the updated private version is not present.
from app.services.sort_analysis import analyze_sort, SortAnalysis
from app.services.persist_zones import persist_zones
from app.services.assign_clusters import AssignmentProposal, ClusterAssignment
from app.services.assign_totes import assign_totes, AnchorPoint
from app.services.cluster_packages import Cluster, ClusterResult, BoundingBox


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COMPANY_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SORT_DATE  = date(2026, 6, 28)
_ACTOR_ID   = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

_TRUCK_A_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_TRUCK_B_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_package(tba: str, bag_id: str, lat: float, lng: float,
                  block_key: str = "W_36_St_300") -> dict:
    """Build an enriched manifest package dict."""
    return {
        "tba": tba,
        "bag_id": bag_id,
        "lat": lat,
        "lng": lng,
        "block_key": block_key,
        "normalised_address": f"300 W 36 STREET",
        "first_cross_street": "8 AVENUE",
        "second_cross_street": "9 AVENUE",
    }


def _make_cluster(cluster_id: int, packages: list[dict], truck_id: UUID) -> ClusterAssignment:
    """Build a minimal ClusterAssignment from a package list."""
    lats = [p["lat"] for p in packages]
    lngs = [p["lng"] for p in packages]
    centroid = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
    bbox = BoundingBox(min(lats), max(lats), min(lngs), max(lngs))
    cluster = Cluster(
        cluster_id=cluster_id,
        packages=packages,
        centroid=centroid,
        bounding_box=bbox,
        polygon=[centroid],  # trivial polygon for test purposes
    )
    return ClusterAssignment(
        cluster=cluster,
        truck_id=truck_id,
        truck_name=f"Truck {'A' if truck_id == _TRUCK_A_ID else 'B'}",
        workload_score=None,
    )


def _make_proposal(
    assignments: list[ClusterAssignment],
    outliers: list[dict] | None = None,
) -> AssignmentProposal:
    return AssignmentProposal(
        assignments=assignments,
        unassigned_clusters=[],
        outliers=outliers or [],
    )


def _make_db():
    """Mock SQLAlchemy session that captures added objects."""
    db = MagicMock()
    added: list = []

    def _add(obj):
        added.append(obj)
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    db.add.side_effect = _add
    db._added = added
    return db


# ---------------------------------------------------------------------------
# 1. Happy path — two trucks, clean bags, zones written
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Bags are perfectly split: Bag-A on Truck A, Bag-B on Truck B."""

    def _build(self):
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-A", 40.750 + i * 0.001, -73.990) for i in range(5)]
        pkgs_b = [_make_package(f"TBA-B{i}", "Bag-B", 40.760 + i * 0.001, -73.980) for i in range(5)]

        assignment_a = _make_cluster(0, pkgs_a, _TRUCK_A_ID)
        assignment_b = _make_cluster(1, pkgs_b, _TRUCK_B_ID)
        proposal = _make_proposal([assignment_a, assignment_b])

        return pkgs_a + pkgs_b, proposal

    def test_zone_tbas_split_by_truck(self):
        packages, proposal = self._build()
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        assert len(zones) == 2
        truck_a_zone = next(z for z in zones if z.truck_id == _TRUCK_A_ID)
        truck_b_zone = next(z for z in zones if z.truck_id == _TRUCK_B_ID)

        assert set(truck_a_zone.package_tbas) == {f"TBA-A{i}" for i in range(5)}
        assert set(truck_b_zone.package_tbas) == {f"TBA-B{i}" for i in range(5)}

    def test_zones_deactivate_prior_zones(self):
        """persist_zones must issue an UPDATE ... SET is_active=False before inserting."""
        packages, proposal = self._build()
        db = _make_db()

        persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        # Verify db.query(...).filter(...).update(...) was called (deactivation step)
        assert db.query.called

    def test_zone_labels_correct(self):
        packages, proposal = self._build()
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        labels = {z.zone_label for z in zones}
        assert "Truck A" in labels
        assert "Truck B" in labels

    def test_zones_have_correct_metadata(self):
        packages, proposal = self._build()
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        for zone in zones:
            assert zone.company_id == _COMPANY_ID
            assert zone.zone_date == _SORT_DATE
            assert zone.created_by == _ACTOR_ID
            assert zone.created_by_name == "Dispatch"
            assert zone.is_active is True


# ---------------------------------------------------------------------------
# 5. Zone → commit-sort handoff
# ---------------------------------------------------------------------------

class TestZoneToCommitSortHandoff:
    """Verify TruckZone.package_tbas contains exactly what commit-sort would use.

    We don't invoke the actual commit-sort HTTP endpoint (it requires Redis +
    the route_sort service). Instead we verify the zone's package_tbas list is
    correct — that is the only input the commit-sort endpoint reads from the DB.
    """

    def test_zone_tbas_are_the_input_to_commit_sort(self):
        """The TBAs in TruckZone.package_tbas must exactly match what was in the cluster."""
        tbas = [f"TBA-{i:03}" for i in range(20)]
        packages = [_make_package(tba, "Bag-X", 40.750 + i * 0.0001, -73.990) for i, tba in enumerate(tbas)]

        assignment = _make_cluster(0, packages, _TRUCK_A_ID)
        proposal = _make_proposal([assignment])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        zone = zones[0]
        # commit-sort reads zone.package_tbas and uses it to filter the Redis manifest.
        # Verify every TBA in the cluster is in the zone, and no extras.
        assert set(zone.package_tbas) == set(tbas)

    def test_multiple_trucks_disjoint_tba_sets(self):
        """No TBA should appear in more than one zone's package_tbas."""
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-A", 40.750, -73.990) for i in range(10)]
        pkgs_b = [_make_package(f"TBA-B{i}", "Bag-B", 40.760, -73.980) for i in range(10)]

        proposal = _make_proposal([
            _make_cluster(0, pkgs_a, _TRUCK_A_ID),
            _make_cluster(1, pkgs_b, _TRUCK_B_ID),
        ])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        tbas_a = set(next(z for z in zones if z.truck_id == _TRUCK_A_ID).package_tbas)
        tbas_b = set(next(z for z in zones if z.truck_id == _TRUCK_B_ID).package_tbas)
        assert tbas_a.isdisjoint(tbas_b), "TBAs must not overlap across zones"



# ---------------------------------------------------------------------------
# 6. assign_totes — tote-level anchored balanced assignment (ADR-169)
# ---------------------------------------------------------------------------

_ANCHOR_A = None  # populated lazily — AnchorPoint may be absent in public CI
_ANCHOR_B = None


def _anchors():
    """Truck A anchored in Chelsea, Truck B anchored in Hell's Kitchen."""
    return [
        AnchorPoint(truck_id=_TRUCK_A_ID, truck_name="Truck A",
                    lat=40.745, lng=-73.995, source="truck_anchor"),
        AnchorPoint(truck_id=_TRUCK_B_ID, truck_name="Truck B",
                    lat=40.762, lng=-73.985, source="truck_anchor"),
    ]


def _tote(bag_id: str, n: int, lat: float, lng: float, spread: float = 0.0005) -> list[dict]:
    """n packages tightly grouped around (lat, lng), all in one tote."""
    return [
        _make_package(f"{bag_id}-TBA{i}", bag_id, lat + (i % 3) * spread, lng + (i % 2) * spread)
        for i in range(n)
    ]


class TestAssignTotes:
    def test_totes_are_never_split_across_trucks(self):
        """Every package of a tote lands on the same truck — tote atomicity."""
        pkgs = []
        # Tote straddling the midpoint: 3 packages nearer A, 2 nearer B
        pkgs += [_make_package(f"MIX-{i}", "Bag-Mix", 40.747, -73.993) for i in range(3)]
        pkgs += [_make_package(f"MIX-B{i}", "Bag-Mix", 40.760, -73.986) for i in range(2)]
        pkgs += _tote("Bag-A1", 5, 40.744, -73.996)
        pkgs += _tote("Bag-B1", 5, 40.763, -73.984)

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        tba_truck = {
            p["tba"]: a.truck_id
            for a in proposal.assignments
            for p in a.cluster.packages
        }
        mix_trucks = {tba_truck[p["tba"]] for p in pkgs if p["bag_id"] == "Bag-Mix"}
        assert len(mix_trucks) == 1, "tote must be assigned wholly to one truck"
        # Majority (3 vs 2) was nearer Truck A
        assert mix_trucks == {_TRUCK_A_ID}

    def test_equity_tote_counts_within_tolerance(self):
        """Tote counts per truck differ by at most 1 after the balance pass."""
        pkgs = []
        # 10 totes near Truck A's anchor, only 2 near Truck B's
        for i in range(10):
            pkgs += _tote(f"Bag-A{i}", 4, 40.744 + i * 0.0008, -73.996)
        for i in range(2):
            pkgs += _tote(f"Bag-B{i}", 4, 40.762 + i * 0.0008, -73.985)

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        totes_per_truck: dict = defaultdict(set)
        for a in proposal.assignments:
            for p in a.cluster.packages:
                totes_per_truck[a.truck_id].add(p["bag_id"])
        counts = [len(v) for v in totes_per_truck.values()]
        assert max(counts) - min(counts) <= 1, f"unbalanced tote counts: {counts}"
        assert sum(counts) == 12

    def test_balance_moves_totes_nearest_to_receiver(self):
        """The totes traded to the underloaded truck are the northernmost
        (closest to Truck B's anchor), keeping zones contiguous."""
        pkgs = []
        for i in range(6):
            # Totes laid south→north; higher i = closer to Truck B
            pkgs += _tote(f"Bag-{i}", 3, 40.744 + i * 0.002, -73.994)

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        truck_b_bags = {
            p["bag_id"]
            for a in proposal.assignments if a.truck_id == _TRUCK_B_ID
            for p in a.cluster.packages
        }
        truck_a_bags = {
            p["bag_id"]
            for a in proposal.assignments if a.truck_id == _TRUCK_A_ID
            for p in a.cluster.packages
        }
        assert len(truck_a_bags) == 3 and len(truck_b_bags) == 3
        # Truck B must hold the northern half, Truck A the southern half
        assert truck_b_bags == {"Bag-3", "Bag-4", "Bag-5"}
        assert truck_a_bags == {"Bag-0", "Bag-1", "Bag-2"}

    def test_coordinate_less_package_rides_with_its_tote(self):
        """A package with no lat/lng still lands on its tote's truck."""
        pkgs = _tote("Bag-A1", 4, 40.744, -73.996)
        rider = {"tba": "TBA-NOCOORD", "bag_id": "Bag-A1", "lat": None, "lng": None,
                 "block_key": None, "normalised_address": None}
        pkgs.append(rider)
        pkgs += _tote("Bag-B1", 5, 40.763, -73.984)

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        all_outlier_tbas = {p["tba"] for p in proposal.outliers}
        assert "TBA-NOCOORD" not in all_outlier_tbas
        tba_truck = {
            p["tba"]: a.truck_id
            for a in proposal.assignments
            for p in a.cluster.packages
        }
        assert tba_truck["TBA-NOCOORD"] == tba_truck["Bag-A1-TBA0"]

    def test_out_of_boundary_tote_becomes_outliers(self):
        """A tote whose centroid is outside the company boundary is not assigned."""
        boundary = [
            {"lat": 40.735, "lng": -74.010},
            {"lat": 40.775, "lng": -74.010},
            {"lat": 40.775, "lng": -73.975},
            {"lat": 40.735, "lng": -73.975},
            {"lat": 40.735, "lng": -74.010},
        ]
        pkgs = _tote("Bag-IN", 5, 40.744, -73.996)
        pkgs += _tote("Bag-OUT", 4, 40.700, -74.015)  # East Village-ish, outside

        proposal = assign_totes(packages=pkgs, anchors=_anchors(), boundary=boundary)

        outlier_tbas = {p["tba"] for p in proposal.outliers}
        assert outlier_tbas == {f"Bag-OUT-TBA{i}" for i in range(4)}
        assigned_tbas = {
            p["tba"] for a in proposal.assignments for p in a.cluster.packages
        }
        assert assigned_tbas == {f"Bag-IN-TBA{i}" for i in range(5)}

    def test_loose_uncoordinated_package_is_outlier(self):
        """No bag_id + no coordinates → nothing to anchor on → outlier."""
        pkgs = _tote("Bag-A1", 5, 40.744, -73.996)
        pkgs.append({"tba": "TBA-LOST", "bag_id": None, "lat": None, "lng": None})

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        assert {p["tba"] for p in proposal.outliers} == {"TBA-LOST"}

    def test_all_packages_covered_by_cluster_or_outlier(self):
        """No package is silently dropped — clusters + outliers == input."""
        pkgs = _tote("Bag-A1", 5, 40.744, -73.996)
        pkgs += _tote("Bag-B1", 5, 40.763, -73.984)
        pkgs.append({"tba": "TBA-LOST", "bag_id": None, "lat": None, "lng": None})

        proposal = assign_totes(packages=pkgs, anchors=_anchors())

        covered = (
            {p["tba"] for a in proposal.assignments for p in a.cluster.packages}
            | {p["tba"] for p in proposal.outliers}
        )
        assert covered == {p["tba"] for p in pkgs}
        assert proposal.unassigned_clusters == []

    def test_two_anchor_truck_can_receive_two_zones(self):
        """A truck with two anchors gets one cluster per anchor with totes,
        but counts as a single truck for equity."""
        anchors = _anchors() + [
            AnchorPoint(truck_id=_TRUCK_A_ID, truck_name="Truck A",
                        lat=40.738, lng=-74.005, source="truck_anchor"),
        ]
        pkgs = []
        pkgs += _tote("Bag-N1", 3, 40.7445, -73.9955)   # near A primary
        pkgs += _tote("Bag-S1", 3, 40.7385, -74.0045)   # near A secondary
        pkgs += _tote("Bag-B1", 3, 40.762, -73.985)
        pkgs += _tote("Bag-B2", 3, 40.763, -73.984)

        proposal = assign_totes(packages=pkgs, anchors=anchors)

        a_zones = [a for a in proposal.assignments if a.truck_id == _TRUCK_A_ID]
        assert len(a_zones) == 2, "two-anchor truck should produce two zones"
        a_bags = {p["bag_id"] for z in a_zones for p in z.cluster.packages}
        assert a_bags == {"Bag-N1", "Bag-S1"}

    def test_clustered_anchors_produce_disjoint_territories(self):
        """Regression for the enveloped-zones bug: with all anchors packed into
        a small central cluster and totes spread over the whole territory, the
        balanced assignment must still tile the area into contiguous cells —
        pairwise convex-hull overlap stays near zero (the old greedy balance
        pass interleaved memberships and every hull covered everything)."""
        import itertools
        from shapely.geometry import MultiPoint

        truck_c = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
        truck_d = uuid.UUID("cccccccc-0000-0000-0000-000000000004")
        anchors = [
            AnchorPoint(truck_id=_TRUCK_A_ID, truck_name="Atlas",  lat=40.7480, lng=-73.9955, source="truck_anchor"),
            AnchorPoint(truck_id=_TRUCK_B_ID, truck_name="Eagle",  lat=40.7530, lng=-73.9925, source="truck_anchor"),
            AnchorPoint(truck_id=truck_c,     truck_name="Falcon", lat=40.7500, lng=-73.9970, source="truck_anchor"),
            AnchorPoint(truck_id=truck_d,     truck_name="Titan",  lat=40.7560, lng=-73.9930, source="truck_anchor"),
        ]

        pkgs = []
        tote = 0
        for i in range(20):
            for j in range(10):
                lat = 40.744 + i * (40.770 - 40.744) / 19
                lng = -74.005 + j * 0.0015
                tote += 1
                pkgs += _tote(f"BAG{tote:04}", 3, lat, lng, spread=0.0001)

        proposal = assign_totes(packages=pkgs, anchors=anchors)

        counts: dict = {}
        polys: dict = {}
        for a in proposal.assignments:
            counts[a.truck_id] = counts.get(a.truck_id, 0) + len({p["bag_id"] for p in a.cluster.packages})
            # the rendered zone polygon is what dispatch sees — assert on it
            polys[a.truck_id] = MultiPoint([(v["lng"], v["lat"]) for v in a.cluster.polygon]).convex_hull

        vals = list(counts.values())
        assert max(vals) - min(vals) <= 1, f"unbalanced: {vals}"

        for (t1, h1), (t2, h2) in itertools.combinations(polys.items(), 2):
            ratio = h1.intersection(h2).area / min(h1.area, h2.area)
            assert ratio < 0.05, f"territories overlap {ratio:.2f} — partition interleaved"

    def test_anchor_source_recorded(self):
        pkgs = _tote("Bag-A1", 5, 40.744, -73.996)
        proposal = assign_totes(packages=pkgs, anchors=_anchors())
        assert all(a.anchor_source == "truck_anchor" for a in proposal.assignments)


# ---------------------------------------------------------------------------
# 6b. persist_zones — per-zone TBA lists and tote counts (ADR-169)
# ---------------------------------------------------------------------------

class TestPerZoneTbasAndToteCounts:
    def test_two_zones_same_truck_have_disjoint_tbas(self):
        """A two-anchor truck gets one zone per anchor; sibling zone rows must
        not duplicate each other's packages (regression: TBA lists were built
        per truck, not per zone)."""
        pkgs_n = [_make_package(f"TBA-N{i}", "Bag-N", 40.750, -73.990) for i in range(4)]
        pkgs_s = [_make_package(f"TBA-S{i}", "Bag-S", 40.738, -74.004) for i in range(3)]

        proposal = _make_proposal([
            _make_cluster(0, pkgs_n, _TRUCK_A_ID),
            _make_cluster(1, pkgs_s, _TRUCK_A_ID),  # same truck, second anchor zone
        ])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        assert len(zones) == 2
        tbas_0 = set(zones[0].package_tbas)
        tbas_1 = set(zones[1].package_tbas)
        assert tbas_0.isdisjoint(tbas_1)
        assert tbas_0 | tbas_1 == {f"TBA-N{i}" for i in range(4)} | {f"TBA-S{i}" for i in range(3)}

    def test_tote_count_persisted_per_zone(self):
        """tote_count = distinct bag_ids in the zone; bagless TBAs count as 1 each."""
        pkgs = [_make_package(f"TBA-A{i}", "Bag-A", 40.750, -73.990) for i in range(3)]
        pkgs += [_make_package(f"TBA-B{i}", "Bag-B", 40.751, -73.991) for i in range(2)]
        loose = _make_package("TBA-LOOSE", "", 40.752, -73.992)
        loose["bag_id"] = None
        pkgs.append(loose)

        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        assert zones[0].tote_count == 3  # Bag-A + Bag-B + 1 loose

    def test_coordinate_less_rider_does_not_break_centroid(self):
        """Zone centroid must average only coordinated packages."""
        pkgs = [_make_package(f"TBA-A{i}", "Bag-A", 40.750, -73.990) for i in range(3)]
        rider = {"tba": "TBA-RIDER", "bag_id": "Bag-A", "lat": None, "lng": None}
        pkgs.append(rider)

        proposal = _make_proposal([_make_cluster(0, pkgs[:3], _TRUCK_A_ID)])
        proposal.assignments[0].cluster.packages = pkgs  # rider included in membership

        db = _make_db()
        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        assert zones[0].centroid_lat == pytest.approx(40.750)
        assert "TBA-RIDER" in zones[0].package_tbas


# ---------------------------------------------------------------------------
# 6c. Station load finalization — roster + re-run diff transfers (ADR-174)
# ---------------------------------------------------------------------------

from app.models.truck_zone import TruckZone as _TZModel
from app.models.tote_ops import ToteTransfer as _TTModel


def _make_db_with_prev(prev_zones, decided_transfers=None):
    """MagicMock session whose TruckZone query returns prev_zones and whose
    ToteTransfer query returns decided_transfers (for the re-run diff path)."""
    db = _make_db()
    tz_chain = MagicMock()
    tz_chain.filter.return_value = tz_chain
    tz_chain.all.return_value = prev_zones
    tt_chain = MagicMock()
    tt_chain.filter.return_value = tt_chain
    tt_chain.all.return_value = decided_transfers or []
    tt_chain.delete.return_value = 0
    # persist_zones also runs db.query(AssignmentMember.employee_id, _TA.truck_id)
    # for dock seeding — a 2-arg query. Accept *models and route only the models this
    # test cares about; anything else (driver rows, DockAssignment) gets a fresh empty
    # MagicMock chain, matching the base _make_db behaviour.
    def _query(*models):
        model = models[0]
        if model is _TZModel:
            return tz_chain
        if model is _TTModel:
            return tt_chain
        return MagicMock()

    db.query.side_effect = _query
    return db


class TestLoadFinalization:
    def _pkg(self, tba, bag, ptype=None, tag=None):
        p = _make_package(tba, bag, 40.750, -73.990)
        p["package_type"] = ptype
        p["tag_number"] = tag
        return p

    def test_roster_persisted_with_ov_and_dock_data(self):
        pkgs = [
            self._pkg("TBA-1", "Bag-A", None, "A-12"),
            self._pkg("TBA-2", "Bag-A", None, "A-12"),
            self._pkg("TBA-3", "Bag-A", "OV_M", "Z-03"),
            self._pkg("TBA-4", "Bag-B", None, "B-07"),
        ]
        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )

        roster = {e["bag_id"]: e for e in zones[0].tote_roster}
        assert set(roster) == {"Bag-A", "Bag-B"}
        a = roster["Bag-A"]
        assert a["package_count"] == 3
        assert a["ov_count"] == 1
        assert a["ov_sizes"] == ["OV_M"]
        assert a["dock_tags"] == ["A-12"]
        assert a["ov_dock_tags"] == ["Z-03"]
        assert set(a["tba_numbers"]) == {"TBA-1", "TBA-2", "TBA-3"}
        # dock-tag ordering: A-12 before B-07
        assert [e["bag_id"] for e in zones[0].tote_roster] == ["Bag-A", "Bag-B"]

    def test_roster_ov_details(self):
        """OVs carry size@zone on the roster entry."""
        pkgs = [
            self._pkg("TBA-1", "Bag-A", None, "A-05"),
            self._pkg("TBA-2", "Bag-A", "OV_L", "OV-2"),
        ]
        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )
        entry = zones[0].tote_roster[0]
        assert entry["ov_details"] == [{"size": "OV_L", "zone": "OV-2"}]
        assert entry["dock_tags"] == ["A-05"]
        assert "classification" not in entry   # retired with tier-1 (ADR-177)

    def test_dock_tags_frequency_ordered(self):
        """A misroute rider's foreign dock tag ranks after the bag's own tag."""
        pkgs = [self._pkg(f"TBA-{i}", "Bag-A", None, "A-05") for i in range(4)]
        pkgs.append(self._pkg("TBA-RIDER", "Bag-A", None, "F-19"))  # misroute's original tag
        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )
        assert zones[0].tote_roster[0]["dock_tags"] == ["A-05", "F-19"]

    def test_rerun_diff_creates_suggested_transfer(self):
        """A bag that moved trucks between runs becomes a suggested transfer
        from its previous (physical) truck to the new one."""
        pkgs_a = [self._pkg(f"TBA-A{i}", "Bag-A") for i in range(3)]
        pkgs_b = [self._pkg(f"TBA-B{i}", "Bag-B") for i in range(3)]

        # Previous run: Bag-A was on Truck B
        prev_zone = MagicMock()
        prev_zone.truck_id = _TRUCK_B_ID
        prev_zone.package_tbas = [f"TBA-A{i}" for i in range(3)]
        db = _make_db_with_prev([prev_zone])

        # New run: Bag-A on Truck A, Bag-B on Truck B
        proposal = _make_proposal([
            _make_cluster(0, pkgs_a, _TRUCK_A_ID),
            _make_cluster(1, pkgs_b, _TRUCK_B_ID),
        ])
        persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )

        transfers = [o for o in db._added if isinstance(o, _TTModel)]
        assert len(transfers) == 1
        t = transfers[0]
        assert t.bag_id == "Bag-A"
        assert t.from_truck_id == _TRUCK_B_ID
        assert t.to_truck_id == _TRUCK_A_ID
        assert t.status == "suggested"
        assert t.reason == "rerun_diff"
        assert t.package_count == 3

    def test_rerun_diff_skips_decided_bags(self):
        """Bags dispatch already decided on (kept/confirmed) are not re-suggested."""
        pkgs_a = [self._pkg(f"TBA-A{i}", "Bag-A") for i in range(3)]
        prev_zone = MagicMock()
        prev_zone.truck_id = _TRUCK_B_ID
        prev_zone.package_tbas = [f"TBA-A{i}" for i in range(3)]
        decided = MagicMock()
        decided.bag_id = "Bag-A"
        decided.status = "confirmed"
        decided.to_truck_id = _TRUCK_A_ID     # decision matches the new assignment
        decided.from_truck_id = _TRUCK_B_ID
        db = _make_db_with_prev([prev_zone], decided_transfers=[decided])

        proposal = _make_proposal([_make_cluster(0, pkgs_a, _TRUCK_A_ID)])
        persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )

        assert [o for o in db._added if isinstance(o, _TTModel)] == []

    def test_rerun_reapplies_kept_decision(self):
        """A re-run must not swallow dispatch's 'keep' decision: the bag's
        zone data follows the kept truck even though the algorithm re-assigns
        it elsewhere, and no new suggestion is raised."""
        pkgs_a = [self._pkg(f"TBA-A{i}", "Bag-A") for i in range(3)]
        pkgs_b = [self._pkg(f"TBA-B{i}", "Bag-B") for i in range(3)]

        prev_zone = MagicMock()
        prev_zone.truck_id = _TRUCK_B_ID
        prev_zone.package_tbas = [f"TBA-A{i}" for i in range(3)]

        kept = MagicMock()
        kept.bag_id = "Bag-A"
        kept.status = "kept"
        kept.from_truck_id = _TRUCK_B_ID   # dispatch said: stays on Truck B
        kept.to_truck_id = _TRUCK_A_ID
        db = _make_db_with_prev([prev_zone], decided_transfers=[kept])

        # Algorithm still wants Bag-A on Truck A
        proposal = _make_proposal([
            _make_cluster(0, pkgs_a, _TRUCK_A_ID),
            _make_cluster(1, pkgs_b, _TRUCK_B_ID),
        ])
        zones = persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )

        zone_b = next(z for z in zones if z.truck_id == _TRUCK_B_ID)
        zone_a = next(z for z in zones if z.truck_id == _TRUCK_A_ID)
        assert {f"TBA-A{i}" for i in range(3)}.issubset(set(zone_b.package_tbas))
        assert set(zone_a.package_tbas).isdisjoint({f"TBA-A{i}" for i in range(3)})
        assert [o for o in db._added if isinstance(o, _TTModel)] == []

    def test_first_run_creates_no_transfers(self):
        pkgs = [self._pkg("TBA-1", "Bag-A")]
        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()   # default MagicMock: prev zones iterate empty

        persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
        )
        assert [o for o in db._added if isinstance(o, _TTModel)] == []


# ---------------------------------------------------------------------------
# 6d. Out-of-zone removals + tier-1 taxonomy (ADR-176)
# ---------------------------------------------------------------------------

_BOUNDARY = [
    {"lat": 40.740, "lng": -74.010},
    {"lat": 40.770, "lng": -74.010},
    {"lat": 40.770, "lng": -73.980},
    {"lat": 40.740, "lng": -73.980},
    {"lat": 40.740, "lng": -74.010},
]
_ANCHORS = [
    {"truck_id": _TRUCK_A_ID, "lat": 40.745, "lng": -73.995},
    {"truck_id": _TRUCK_B_ID, "lat": 40.762, "lng": -73.985},
]


class TestSortAnalysis:
    """ADR-177: non-blocking action lists replace the tier-1 review wall."""

    def _pkg(self, tba, bag, lat, lng, ptype=None, tag=None, block="W_36_St_300"):
        p = _make_package(tba, bag, lat, lng, block_key=block)
        p["package_type"] = ptype
        p["tag_number"] = tag
        return p

    def test_ooz_tote_is_station_removal(self):
        ooz = [self._pkg(f"TBA-Q{i}", "Bag-OOZ", 40.700, -74.020, tag="A-14") for i in range(3)]
        good = [self._pkg(f"TBA-G{i}", "Bag-Good", 40.745, -73.995) for i in range(3)]

        proposal = _make_proposal([_make_cluster(0, good, _TRUCK_A_ID)], outliers=ooz)
        analysis = analyze_sort(proposal, good + ooz, boundary=_BOUNDARY)

        assert len(analysis.station_removals) == 1
        cand = analysis.station_removals[0]
        assert cand["bag_id"] == "Bag-OOZ"
        assert cand["package_count"] == 3
        assert cand["locator"] == "A-14"
        assert analysis.ap_flags == []
        assert analysis.unplaced_bags == []

    def test_ooz_rider_is_ap_flag(self):
        """An out-of-zone rider inside a good tote is pulled at the ANCHOR
        POINT (ADR-177 decision c), not the dock."""
        pkgs = [self._pkg(f"TBA-{i}", "Bag-A", 40.745, -73.995) for i in range(9)]
        rider = self._pkg("TBA-RIDER", "Bag-A", 40.700, -74.020, tag="F-02", block="OTHER_BLOCK")
        packages = pkgs + [rider]

        proposal = _make_proposal([_make_cluster(0, packages, _TRUCK_A_ID)])
        analysis = analyze_sort(proposal, packages, boundary=_BOUNDARY)

        assert analysis.ap_flags == [{"bag_id": "Bag-A", "tba": "TBA-RIDER", "locator": "F-02"}]
        assert analysis.station_removals == []

    def test_unplaced_tote_reported(self):
        """A tote with zero geocoded packages is a manual dispatch decision."""
        blind = []
        for i in range(3):
            p = self._pkg(f"TBA-B{i}", "Bag-Blind", 0, 0)
            p["lat"] = None
            p["lng"] = None
            blind.append(p)
        proposal = _make_proposal([], outliers=blind)
        analysis = analyze_sort(proposal, blind, boundary=_BOUNDARY)

        assert analysis.unplaced_bags == [{"bag_id": "Bag-Blind", "package_count": 3}]
        assert analysis.station_removals == []

    def test_coherent_boundary_tote_produces_nothing(self):
        """Packages coherent with their tote inherit its legitimacy — a
        boundary tote placed by the equity solver yields no flags at all."""
        packages = [self._pkg(f"TBA-{i}", "Bag-Edge", 40.758, -73.987) for i in range(6)]
        proposal = _make_proposal([_make_cluster(0, packages, _TRUCK_A_ID)])
        analysis = analyze_sort(proposal, packages, boundary=_BOUNDARY)
        assert analysis.station_removals == [] and analysis.ap_flags == [] and analysis.unplaced_bags == []

    def test_persist_writes_removals_with_pull_points(self):
        from app.models.tote_ops import PackageRemoval as _PRModel
        pkgs = [self._pkg(f"TBA-{i}", "Bag-A", 40.745, -73.995) for i in range(3)]
        proposal = _make_proposal([_make_cluster(0, pkgs, _TRUCK_A_ID)])
        db = _make_db()

        persist_zones(
            proposal=proposal, zone_date=_SORT_DATE, company_id=_COMPANY_ID,
            created_by=_ACTOR_ID, created_by_name="Dispatch", db=db,
            station_removals=[{
                "bag_id": "Bag-OOZ", "tba_numbers": ["TBA-Q0", "TBA-Q1"],
                "package_count": 2, "locator": "A-14",
            }],
            ap_flags=[{"bag_id": "Bag-A", "tba": "TBA-RIDER", "locator": "F-02"}],
        )

        removals = [o for o in db._added if isinstance(o, _PRModel)]
        assert len(removals) == 2
        by_point = {r.pull_point: r for r in removals}
        assert by_point["station"].whole_tote is True
        assert by_point["station"].bag_id == "Bag-OOZ"
        assert by_point["anchor_point"].whole_tote is False
        assert by_point["anchor_point"].tba == "TBA-RIDER"
        assert all(r.status == "flagged" for r in removals)
        # handoff_status defaults to 'pending' at the DB level (ADR-178) — the
        # column default fires on insert, so it is None on unflushed objects.
        assert by_point["anchor_point"].handoff_status in (None, "pending")

# ---------------------------------------------------------------------------
# 7. Empty manifest — edge case
# ---------------------------------------------------------------------------

class TestEmptyManifest:
    def test_empty_analysis(self):
        proposal = _make_proposal([])
        analysis = analyze_sort(proposal, [], boundary=_BOUNDARY)
        assert analysis.station_removals == []
        assert analysis.ap_flags == []
        assert analysis.unplaced_bags == []

    def test_empty_cluster_result_produces_no_zones(self):
        proposal = _make_proposal([])
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        assert zones == []
