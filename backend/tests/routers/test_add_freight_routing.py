"""Unit tests for mid-day freight best-fit routing (ADR-184).

Covers the pure nearest-centroid decision (_nearest_truck_by_coords): NO
balancing, nearest zone centroid wins, missing centroids skipped.

app.routers.sort imports proprietary services (route_sort, seed_manifest,
assign_totes) that are absent in public CI — skip the whole module if so.
"""
import uuid
import pytest

try:
    from app.routers.sort import _nearest_truck_by_coords
except ImportError:
    pytest.skip("proprietary sort deps not available (CI skip)", allow_module_level=True)


def test_picks_nearest_centroid():
    a, b = uuid.uuid4(), uuid.uuid4()
    # b's centroid is much closer to the target point than a's
    cands = [(a, 40.80, -73.95), (b, 40.75, -73.99)]
    assert _nearest_truck_by_coords(40.752, -73.991, cands) == b


def test_no_balancing_just_distance():
    # Even if 'a' were the "busy" truck, distance alone decides — nearest wins.
    near, far = uuid.uuid4(), uuid.uuid4()
    cands = [(far, 41.10, -73.50), (near, 40.7501, -73.9910)]
    assert _nearest_truck_by_coords(40.7500, -73.9900, cands) == near


def test_skips_missing_centroids():
    good, blank = uuid.uuid4(), uuid.uuid4()
    cands = [(blank, None, None), (good, 40.75, -73.99)]
    assert _nearest_truck_by_coords(40.75, -73.99, cands) == good


def test_none_when_no_usable_candidate():
    only = uuid.uuid4()
    assert _nearest_truck_by_coords(40.75, -73.99, [(only, None, None)]) is None
    assert _nearest_truck_by_coords(40.75, -73.99, []) is None
