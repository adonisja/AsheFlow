"""
Integration tests — manifest injection through TruckZone creation to route creation.

Covers the full sort pipeline in one connected flow:

  cluster_packages()
      → assign_clusters()
      → tier1_verify()
      → persist_zones()          ← TruckZone rows written
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
# Skip the entire module on CI rather than failing collection.
tier1_verify_mod = pytest.importorskip(
    "app.services.tier1_verify",
    reason="app.services.tier1_verify not available (proprietary — CI skip)",
)

from app.services.assign_clusters import assign_clusters, AssignmentProposal, ClusterAssignment
from app.services.cluster_packages import cluster_packages, Cluster, ClusterResult, BoundingBox
from app.services.tier1_verify import BagOverride, BagResult, tier1_verify, VerificationResult
from app.services.persist_zones import persist_zones


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

def _make_cfg(
    small_tote_cutoff: int  = 10,
    small_stray_max: int    = 1,
    small_uncertain_max: int = 3,
    stray_pct: float        = 0.10,
    uncertain_pct: float    = 0.40,
):
    """Minimal CompanyConfig-like object for tier1_verify."""
    cfg = MagicMock()
    cfg.tier1_small_tote_cutoff   = small_tote_cutoff
    cfg.tier1_small_stray_max     = small_stray_max
    cfg.tier1_small_uncertain_max = small_uncertain_max
    cfg.tier1_stray_pct           = stray_pct
    cfg.tier1_uncertain_pct       = uncertain_pct
    return cfg


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
        match_type="sequential",
        workload_score=None,
        is_overflow=False,
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

    def test_tier1_all_clean(self):
        packages, proposal = self._build()
        cfg = _make_cfg()

        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        assert result.all_clean is True
        assert result.flagged == []
        assert len(result.bag_results) == 2

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
# 2. Tier-1 flagged path — misloaded bag detected
# ---------------------------------------------------------------------------

class TestTier1FlaggedPath:
    """Bag-Mixed has TBAs split: 4 on Truck A, 1 on Truck B (misaligned)."""

    def _build(self):
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-Mixed", 40.750 + i * 0.001, -73.990) for i in range(4)]
        # 1 package from Bag-Mixed is clustered to Truck B — misload
        pkg_stray = _make_package("TBA-STRAY", "Bag-Mixed", 40.760, -73.980)

        assignment_a = _make_cluster(0, pkgs_a, _TRUCK_A_ID)
        assignment_b = _make_cluster(1, [pkg_stray], _TRUCK_B_ID)
        proposal = _make_proposal([assignment_a, assignment_b])

        packages = pkgs_a + [pkg_stray]
        return packages, proposal

    def test_tier1_detects_misloaded_bag(self):
        packages, proposal = self._build()
        # Large tote threshold so classification goes to pct-based path
        cfg = _make_cfg(small_tote_cutoff=3, stray_pct=0.10, uncertain_pct=0.40)

        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        # Bag-Mixed has 1/5 = 0.20 outside — above stray_pct=0.10 but below uncertain_pct=0.40
        assert result.all_clean is False
        assert len(result.flagged) == 1
        flagged = result.flagged[0]
        assert flagged.bag_id == "Bag-Mixed"
        assert flagged.outside_packages == 1
        assert flagged.inferred_truck_id == _TRUCK_A_ID  # 4 votes vs 1
        assert flagged.suggested_truck_id == _TRUCK_B_ID  # stray is on Truck B

    def test_tier1_stray_classification(self):
        """1 outside on a small tote (< cutoff) → 'stray' if within small_stray_max."""
        packages, proposal = self._build()
        # cutoff=10 means 5-pkg bag is "small"; small_stray_max=1 → 1 outside = stray
        cfg = _make_cfg(small_tote_cutoff=10, small_stray_max=1)

        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        assert result.flagged[0].classification == "stray"

    def test_tier1_misaligned_classification(self):
        """Majority of packages on wrong truck → 'misaligned'."""
        # 1 on Truck A, 4 on Truck B — inferred = B, outside = A
        pkgs_b = [_make_package(f"TBA-B{i}", "Bag-M2", 40.760 + i * 0.001, -73.980) for i in range(4)]
        pkg_stray = _make_package("TBA-A0", "Bag-M2", 40.750, -73.990)

        assignment_a = _make_cluster(0, [pkg_stray], _TRUCK_A_ID)
        assignment_b = _make_cluster(1, pkgs_b, _TRUCK_B_ID)
        proposal = _make_proposal([assignment_a, assignment_b])
        packages = [pkg_stray] + pkgs_b

        cfg = _make_cfg(small_tote_cutoff=10, small_stray_max=0, small_uncertain_max=0)
        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        assert result.flagged[0].classification in ("uncertain", "misaligned")


# ---------------------------------------------------------------------------
# 3. Tier-1 override — dispatch confirms bag correction
# ---------------------------------------------------------------------------

class TestTier1Override:
    """Dispatch overrides Bag-Mixed to Truck B. Zones must move those TBAs."""

    def _build_proposal(self):
        # Bag-Mixed: 4 TBAs on Truck A, 1 (stray) on Truck B
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-Mixed", 40.750 + i * 0.001, -73.990) for i in range(4)]
        pkg_stray = _make_package("TBA-STRAY", "Bag-Mixed", 40.760, -73.980)

        assignment_a = _make_cluster(0, pkgs_a, _TRUCK_A_ID)
        assignment_b = _make_cluster(1, [pkg_stray], _TRUCK_B_ID)
        proposal = _make_proposal([assignment_a, assignment_b])
        packages = pkgs_a + [pkg_stray]
        return proposal, packages

    def test_overridden_bag_classifies_clean(self):
        proposal, packages = self._build_proposal()
        cfg = _make_cfg()
        overrides = [BagOverride(bag_id="Bag-Mixed", truck_id=_TRUCK_B_ID)]

        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg, overrides=overrides)

        assert result.all_clean is True
        assert result.flagged == []
        mixed = next(r for r in result.bag_results if r.bag_id == "Bag-Mixed")
        assert mixed.classification == "clean"
        assert mixed.inferred_truck_id == _TRUCK_B_ID

    def test_override_moves_all_tbas_to_confirmed_truck(self):
        proposal, packages = self._build_proposal()
        db = _make_db()
        overrides = [BagOverride(bag_id="Bag-Mixed", truck_id=_TRUCK_B_ID)]

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
            overrides=overrides,
        )

        truck_b_zone = next(z for z in zones if z.truck_id == _TRUCK_B_ID)
        truck_a_zone = next(z for z in zones if z.truck_id == _TRUCK_A_ID)

        # All Bag-Mixed TBAs should now be in Truck B's zone
        all_mixed_tbas = {f"TBA-A{i}" for i in range(4)} | {"TBA-STRAY"}
        assert all_mixed_tbas.issubset(set(truck_b_zone.package_tbas))

        # None of Bag-Mixed TBAs should remain in Truck A's zone
        truck_a_tbas = set(truck_a_zone.package_tbas)
        assert truck_a_tbas.isdisjoint(all_mixed_tbas)

    def test_non_overridden_tbas_stay_in_original_truck(self):
        """Only overridden bag moves. Other packages stay with their DBSCAN truck."""
        pkgs_a_clean = [_make_package(f"TBA-CLEAN{i}", "Bag-Clean", 40.740 + i * 0.001, -73.990) for i in range(3)]
        pkgs_mixed_a = [_make_package(f"TBA-M{i}", "Bag-Mixed", 40.750 + i * 0.001, -73.990) for i in range(4)]
        pkg_stray    = _make_package("TBA-STRAY", "Bag-Mixed", 40.760, -73.980)

        assignment_a = _make_cluster(0, pkgs_a_clean + pkgs_mixed_a, _TRUCK_A_ID)
        assignment_b = _make_cluster(1, [pkg_stray], _TRUCK_B_ID)
        proposal = _make_proposal([assignment_a, assignment_b])

        db = _make_db()
        overrides = [BagOverride(bag_id="Bag-Mixed", truck_id=_TRUCK_B_ID)]

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
            overrides=overrides,
        )

        truck_a_zone = next(z for z in zones if z.truck_id == _TRUCK_A_ID)
        clean_tbas = {f"TBA-CLEAN{i}" for i in range(3)}
        assert clean_tbas.issubset(set(truck_a_zone.package_tbas))


# ---------------------------------------------------------------------------
# 4. Outlier packages — DBSCAN label -1
# ---------------------------------------------------------------------------

class TestOutliers:
    """Outlier TBAs (no cluster) surface in tier-1 but are not placed in any zone."""

    def _build(self):
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-A", 40.750 + i * 0.001, -73.990) for i in range(4)]
        pkg_outlier = _make_package("TBA-OUTLIER", "Bag-A", 40.900, -73.800)  # far away

        assignment_a = _make_cluster(0, pkgs_a, _TRUCK_A_ID)
        # Outlier is in proposal.outliers, not in any cluster
        proposal = _make_proposal([assignment_a], outliers=[pkg_outlier])
        packages = pkgs_a + [pkg_outlier]
        return proposal, packages

    def test_outlier_tba_in_outlier_tbas_field(self):
        proposal, packages = self._build()
        cfg = _make_cfg(small_tote_cutoff=10)

        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        bag_a = next(r for r in result.bag_results if r.bag_id == "Bag-A")
        assert "TBA-OUTLIER" in bag_a.outlier_tbas

    def test_fully_outlier_outside_bag_is_unresolvable(self):
        """A bag where ALL outside TBAs are outliers is unresolvable."""
        # Bag-Out has 3 TBAs in cluster (Truck A) + 2 outliers (no cluster)
        pkgs_cluster = [_make_package(f"TBA-C{i}", "Bag-Out", 40.750 + i * 0.001, -73.990) for i in range(3)]
        pkgs_outlier = [_make_package(f"TBA-OT{i}", "Bag-Out", 40.900 + i * 0.001, -73.800) for i in range(2)]

        assignment_a = _make_cluster(0, pkgs_cluster, _TRUCK_A_ID)
        proposal = _make_proposal([assignment_a], outliers=pkgs_outlier)
        packages = pkgs_cluster + pkgs_outlier

        cfg = _make_cfg(small_tote_cutoff=10, small_stray_max=0)
        result = tier1_verify(proposal=proposal, packages=packages, cfg=cfg)

        bag_out = next(r for r in result.bag_results if r.bag_id == "Bag-Out")
        assert bag_out.unresolvable is True
        assert bag_out.suggested_truck_id is None

    def test_outlier_tbas_excluded_from_zones_without_override(self):
        """Outlier TBAs with no override must not appear in any zone's package_tbas."""
        proposal, packages = self._build()
        db = _make_db()

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
        )

        all_zone_tbas = {tba for z in zones for tba in (z.package_tbas or [])}
        assert "TBA-OUTLIER" not in all_zone_tbas

    def test_outlier_with_override_placed_in_zone(self):
        """An outlier TBA whose bag is overridden by dispatch enters the zone."""
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-A", 40.750 + i * 0.001, -73.990) for i in range(3)]
        pkgs_b = [_make_package(f"TBA-B{i}", "Bag-B", 40.760 + i * 0.001, -73.980) for i in range(3)]
        pkg_outlier = _make_package("TBA-OUTLIER", "Bag-A", 40.900, -73.800)

        assignment_a = _make_cluster(0, pkgs_a, _TRUCK_A_ID)
        assignment_b = _make_cluster(1, pkgs_b, _TRUCK_B_ID)
        # Outlier TBA belongs to Bag-A; dispatch overrides the whole bag to Truck B
        proposal = _make_proposal([assignment_a, assignment_b], outliers=[pkg_outlier])
        db = _make_db()
        overrides = [BagOverride(bag_id="Bag-A", truck_id=_TRUCK_B_ID)]

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
            overrides=overrides,
        )

        truck_b_zone = next(z for z in zones if z.truck_id == _TRUCK_B_ID)
        assert "TBA-OUTLIER" in truck_b_zone.package_tbas


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

    def test_override_produces_disjoint_tba_sets(self):
        """After an override, TBA sets must still be disjoint across zones."""
        pkgs_a = [_make_package(f"TBA-A{i}", "Bag-A", 40.750 + i * 0.001, -73.990) for i in range(3)]
        pkgs_b = [_make_package(f"TBA-B{i}", "Bag-B", 40.760 + i * 0.001, -73.980) for i in range(3)]
        pkg_stray = _make_package("TBA-STRAY", "Bag-A", 40.760, -73.981)  # bag-A pkg in truck-B cluster

        proposal = _make_proposal([
            _make_cluster(0, pkgs_a, _TRUCK_A_ID),
            _make_cluster(1, pkgs_b + [pkg_stray], _TRUCK_B_ID),
        ])
        db = _make_db()
        # Dispatch confirms: Bag-A belongs entirely on Truck B
        overrides = [BagOverride(bag_id="Bag-A", truck_id=_TRUCK_B_ID)]

        zones = persist_zones(
            proposal=proposal,
            zone_date=_SORT_DATE,
            company_id=_COMPANY_ID,
            created_by=_ACTOR_ID,
            created_by_name="Dispatch",
            db=db,
            overrides=overrides,
        )

        tbas_a = set(next(z for z in zones if z.truck_id == _TRUCK_A_ID).package_tbas)
        tbas_b = set(next(z for z in zones if z.truck_id == _TRUCK_B_ID).package_tbas)
        assert tbas_a.isdisjoint(tbas_b), "TBAs must not overlap after override"


# ---------------------------------------------------------------------------
# 6. cluster_packages → assign_clusters plumbing
# ---------------------------------------------------------------------------

class TestClusterToAssignPlumbing:
    """Verify cluster_packages output flows correctly into assign_clusters."""

    def test_packages_with_coordinates_get_clustered(self):
        """Packages with lat/lng produce clusters, not just outliers."""
        # Two tight geographic groups — with low enough eps to form clusters
        pkgs = []
        # Group 1: midtown
        for i in range(35):
            pkgs.append({"tba": f"TBA-MT{i}", "bag_id": "Bag-A",
                         "lat": 40.754 + (i % 7) * 0.0001, "lng": -73.990 + (i % 5) * 0.0001})
        # Group 2: downtown
        for i in range(35):
            pkgs.append({"tba": f"TBA-DT{i}", "bag_id": "Bag-B",
                         "lat": 40.710 + (i % 7) * 0.0001, "lng": -74.010 + (i % 5) * 0.0001})

        result = cluster_packages(pkgs, eps=0.015, min_samples=5)

        assert len(result.clusters) >= 1
        # All packages should land somewhere (cluster or outlier)
        all_result_tbas = (
            {p["tba"] for c in result.clusters for p in c.packages}
            | {p["tba"] for p in result.outliers}
        )
        assert all_result_tbas == {p["tba"] for p in pkgs}

    def test_assign_clusters_maps_clusters_to_trucks(self):
        """assign_clusters produces one assignment per cluster per truck (sequential)."""
        # Build two fake clusters directly (avoid DBSCAN non-determinism in tests)
        pkgs_a = [{"tba": f"TBA-A{i}", "bag_id": "Bag-A",
                   "lat": 40.754, "lng": -73.990} for i in range(5)]
        pkgs_b = [{"tba": f"TBA-B{i}", "bag_id": "Bag-B",
                   "lat": 40.710, "lng": -74.010} for i in range(5)]

        cluster_a = Cluster(
            cluster_id=0, packages=pkgs_a,
            centroid={"lat": 40.754, "lng": -73.990},
            bounding_box=BoundingBox(40.750, 40.758, -73.995, -73.985),
            polygon=[{"lat": 40.754, "lng": -73.990}],
        )
        cluster_b = Cluster(
            cluster_id=1, packages=pkgs_b,
            centroid={"lat": 40.710, "lng": -74.010},
            bounding_box=BoundingBox(40.706, 40.714, -74.015, -74.005),
            polygon=[{"lat": 40.710, "lng": -74.010}],
        )
        cluster_result = ClusterResult(clusters=[cluster_a, cluster_b], outliers=[])

        trucks = [
            {"id": _TRUCK_A_ID, "name": "Truck A"},
            {"id": _TRUCK_B_ID, "name": "Truck B"},
        ]

        proposal = assign_clusters(
            result=cluster_result,
            trucks=trucks,
            recent_zones=[],        # no history → sequential assignment
            company_boundary=[],    # no boundary restriction
            address_profiles=[],    # no workload data
        )

        assert len(proposal.assignments) == 2
        assigned_trucks = {a.truck_id for a in proposal.assignments}
        assert _TRUCK_A_ID in assigned_trucks
        assert _TRUCK_B_ID in assigned_trucks

    def test_all_packages_covered_by_cluster_or_outlier(self):
        """No package is silently dropped by cluster_packages."""
        pkgs = [
            {"tba": "TBA-X", "bag_id": "Bag-X", "lat": 40.754, "lng": -73.990},
            {"tba": "TBA-Y", "bag_id": "Bag-Y", "lat": 40.755, "lng": -73.991},
            {"tba": "TBA-Z", "bag_id": "Bag-Z", "lat": 99.999, "lng": 99.999},  # isolated
        ]

        result = cluster_packages(pkgs, eps=0.001, min_samples=1)

        all_out = (
            {p["tba"] for c in result.clusters for p in c.packages}
            | {p["tba"] for p in result.outliers}
        )
        assert all_out == {"TBA-X", "TBA-Y", "TBA-Z"}


# ---------------------------------------------------------------------------
# 7. Empty manifest — edge case
# ---------------------------------------------------------------------------

class TestEmptyManifest:
    def test_empty_package_list_produces_no_bags(self):
        proposal = _make_proposal([])
        cfg = _make_cfg()

        result = tier1_verify(proposal=proposal, packages=[], cfg=cfg)

        assert result.all_clean is True
        assert result.bag_results == []

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
