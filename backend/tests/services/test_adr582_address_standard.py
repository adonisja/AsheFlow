"""ADR-582: one address standard — the city's spelling, a house number that keeps
its hyphen and letter, never a unit, never a name.

Measured 2026-10-23 against AddressPoint: 29 city street names (1,561 addresses)
that no rule fold gets right, and 35% of the city's house numbers carry a hyphen
or a letter. These tests pin the standard against that real vocabulary.
"""
import json
import pathlib
import re

import pytest

from app.services.derive_block_key import derive_block_key
from app.services.door_key import NOISE_PATTERN, borough_code, canonical_address, door_identity

LEXICON = pathlib.Path(__file__).resolve().parents[2] / "app" / "data" / "street_lexicon.json"
TS = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "utils" / "addressProfile.ts"


def test_every_city_street_name_is_already_canonical():
    """Idempotence over the target vocabulary: the city's spelling never changes."""
    data = json.loads(LEXICON.read_text())["boroughs"]
    bad = [(b, n, canonical_address("1 " + n, b)) for b, names in data.items() for n in names
           if canonical_address("1 " + n, b) != "1 " + n]
    assert sum(len(v) for v in data.values()) > 9000, "the lexicon looks truncated"
    assert not bad, f"{len(bad)} city names are rewritten, e.g. {bad[:5]}"


@pytest.mark.parametrize("raw,boro,want", [
    ("Jane Sample 350 Fifth Avenue #4B", None, "350 5 AVE"),       # name + unit dropped
    ("Jane Sample 350 5th Ave Apt 12B", "1", "350 5 AVE"),
    ("1 West Street", "manhattan", "1 WEST ST"),                    # a direction that IS the name
    ("2 South Avenue", "5", "2 SOUTH AVE"),
    ("1 Hollis Ct Blvd", "4", "1 HOLLIS CT BOULEVARD"),             # a type word inside a name
    ("12 North St", "bronx", "12 NORTH ST"),                        # two streets share a fold key
    ("12 N St", "bronx", "12 N ST"),
    ("455a W 32nd St, Apt 3", "1", "455A W 32 ST"),                 # lettered house number
    ("123 - 45 145th Street", "queens", "123-45 145 ST"),           # Queens
    ("10-1A Beach 9th Street", "4", "10-1A BEACH 9 ST"),
    ("350 5th Ave New York NY 10118", "1", "350 5 AVE"),            # city and zip after the street
    ("433 West 32nd Street, Apt 4", None, "433 W 32 ST"),
    ("350 5 AVENUE", None, "350 5 AVE"),                            # GeoClient's long form
])
def test_the_standard(raw, boro, want):
    assert canonical_address(raw, boro) == want


@pytest.mark.parametrize("raw", [
    "Jane Sample 350 5th Ave", "MR J SAMPLE 1 WEST ST", "c/o Front Desk 433 W 32 ST",
])
def test_nothing_before_the_house_number_survives(raw):
    out = canonical_address(raw)
    assert out[0].isdigit()
    assert not re.search(r"SAMPLE|MR|FRONT DESK|C/O", out)


@pytest.mark.parametrize("raw", ["350 5 AVE APT 12B", "350 5 AVE FL 3", "350 5 AVE #4B", "350 5 AVE UNIT 9"])
def test_no_unit_is_ever_kept(raw):
    assert canonical_address(raw, "1") == "350 5 AVE"


def test_door_identity_is_borough_plus_the_standard():
    assert door_identity("Manhattan", "433 West 32nd Street Apt 4") == ("1", "433 W 32 ST")
    assert borough_code("staten island") == "5" and borough_code("nowhere") is None


@pytest.mark.parametrize("addr,key", [
    ("455A W 32 ST", "W_32_St_400"),        # lettered: same block as its digits
    ("10-1A BEACH 9 ST", "Beach_9_St_10"),  # Queens lettered: cross-street locator
    ("1 WEST ST", "West_St_0"),             # direction + type is a named street
    ("2 SOUTH AVE", "South_Ave_0"),
    ("47-10 VERNON BLVD", "Vernon_Blvd_47"),
    ("100 WEST END AVE", "West_End_Ave_100"),
])
def test_every_house_number_shape_gets_a_block(addr, key):
    assert getattr(derive_block_key(addr, tba=""), "block_key", None) == key


def test_the_web_twin_shares_the_rule_tables():
    """ADR-582 D6: canonicalAddress() previews with the rule fold; its noise words
    and street types must be the server's, or the preview drifts from the rule."""
    ts = TS.read_text()
    py_noise = re.search(r"\\b\(([^)]*)\)\\b", NOISE_PATTERN).group(1).split("|")
    ts_noise = re.search(r"const _NOISE = /\\b\(([^)]*)\)\\b", ts).group(1).split("|")
    assert py_noise == ts_noise
    for word in ("street|st", "avenue|ave|av", "boulevard|blvd", "parkway|pkwy"):
        assert word in ts
