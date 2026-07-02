"""Intersection-form anchor input parsing (ADR-173).

Pure-function tests — no DB or GeoClient. The geocode round-trip is covered by
the endpoint's 422 paths and manual verification against GeoClient v2.
"""
import pytest

try:
    from app.routers.trucks import _parse_intersection_input
except ImportError:
    pytest.skip("trucks router not importable", allow_module_level=True)


@pytest.mark.parametrize("raw,expected", [
    ("W 28 ST & 9 AVE", ("W 28 ST", "9 AVE")),
    ("W 28 ST&9 AVE", ("W 28 ST", "9 AVE")),
    ("28th St and 9th Ave", ("28th St", "9th Ave")),
    ("W 43rd St AND 10th Ave", ("W 43rd St", "10th Ave")),
])
def test_intersection_forms_split(raw, expected):
    assert _parse_intersection_input(raw) == expected


@pytest.mark.parametrize("raw", [
    "365 W 28 ST",           # plain address
    "GRAND ST",              # 'and' inside a word must not split
    "100 ST NICHOLAS AVE",
    "250 BROADWAY",
])
def test_addresses_do_not_split(raw):
    assert _parse_intersection_input(raw) is None


def test_split_is_binary_only():
    # Only the FIRST separator splits — the rest stays in cross street two.
    assert _parse_intersection_input("A ST & B AVE & C BLVD") == ("A ST", "B AVE & C BLVD")
