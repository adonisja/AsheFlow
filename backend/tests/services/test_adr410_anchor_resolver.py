"""ADR-410 — the anchor point identifies the truck.

Every coordinate here is from the verified NYCD export of 2026-09-09, not
invented. The two pairs that matter are the close ones: Morgan and Titan sit
34 m apart, Atlas and Falcon 73 m. Any nearest-neighbour match wide enough to
absorb GPS noise is also wide enough to return the wrong truck for those pairs,
which is why D3 matches exactly on a 5dp key.
"""
from app.services.resolve_truck_anchor import ANCHOR_DP, anchor_key, haversine_m

# The verified mapping (ADR-410 context).
MORGAN = (40.76066, -73.99086)   # BTR43 on 2026-09-09
ATLAS  = (40.75643, -73.99744)   # BTR44
VIKING = (40.76352, -73.99244)   # BTR45
EAGLE  = (40.76017, -73.99551)   # BTR46
TITAN  = (40.76061, -73.99126)   # BTR47
FALCON = (40.75603, -73.99675)   # BTR48

ALL = [MORGAN, ATLAS, VIKING, EAGLE, TITAN, FALCON]


def test_five_dp_keys_are_unique_across_the_fleet():
    """The premise of D3: exact matching only works if the keys distinguish."""
    keys = {anchor_key(lat, lng) for lat, lng in ALL}
    assert len(keys) == len(ALL)


def test_the_close_pairs_are_genuinely_distinct_trucks():
    """Morgan/Titan and Atlas/Falcon are why the match is exact, not nearest.

    If either pair ever collapses to one key, D3's reasoning is void and the
    resolver would silently start answering with whichever row came back first.
    """
    assert haversine_m(*MORGAN, *TITAN) < 50
    assert haversine_m(*ATLAS, *FALCON) < 100
    assert anchor_key(*MORGAN) != anchor_key(*TITAN)
    assert anchor_key(*ATLAS) != anchor_key(*FALCON)


def test_anchor_key_rounds_rather_than_comparing_raw_floats():
    """The columns are double precision. A key built from a float that survived
    a JSON round-trip must still equal the stored one."""
    lat, lng = MORGAN
    assert anchor_key(lat, lng) == anchor_key(lat + 1e-9, lng - 1e-9)
    assert anchor_key(lat, lng) != anchor_key(lat + 1e-4, lng)


def test_anchor_key_is_none_when_either_half_is_missing():
    """A half-parsed anchor must not match anything — including another
    half-parsed one. None is the only safe answer."""
    assert anchor_key(None, None) is None
    assert anchor_key(40.76066, None) is None
    assert anchor_key(None, -73.99086) is None


def test_anchor_dp_matches_the_printed_precision():
    """The sheet prints 5 decimals (~1 m). Rounding harder would merge trucks."""
    assert ANCHOR_DP == 5
    lat, lng = MORGAN
    assert anchor_key(lat, lng) == (40.76066, -73.99086)


def test_haversine_is_metres_not_kilometres():
    """distance_m in the drift audit is only honest if the unit is right."""
    assert 30 < haversine_m(*MORGAN, *TITAN) < 40
