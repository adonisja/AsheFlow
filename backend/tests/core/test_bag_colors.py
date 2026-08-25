"""bag_colors — parse the physical bag color from a manifest label (ADR-230).
Public module (no proprietary imports), so this test runs in public CI."""
from app.core.bag_colors import (
    BAG_COLOR_HEX, _LEGACY_HEX_TO_NAME, canonical_hex, color_hex,
    color_name_for_hex, parse_bag_label,
)


def test_parses_color_and_number():
    assert parse_bag_label("Orange 6218") == ("6218", BAG_COLOR_HEX["orange"])
    assert parse_bag_label("Green 5270")  == ("5270", BAG_COLOR_HEX["green"])
    assert parse_bag_label("Yellow 0483") == ("0483", BAG_COLOR_HEX["yellow"])


def test_blue_is_navy_alias():
    assert parse_bag_label("Blue 12") == ("12", BAG_COLOR_HEX["navy"])
    assert parse_bag_label("Navy 12") == ("12", BAG_COLOR_HEX["navy"])


def test_number_only_has_no_color():
    assert parse_bag_label("6218") == ("6218", None)


def test_unknown_color_keeps_label_no_color():
    # An unrecognised leading word isn't treated as a color; whole string is the id.
    bag_id, hexv = parse_bag_label("Purple 9")
    assert hexv is None
    assert bag_id == "Purple 9"


def test_empty_and_none():
    assert parse_bag_label(None) == (None, None)
    assert parse_bag_label("") == (None, None)


def test_color_hex_resolves_aliases():
    assert color_hex("orange") == BAG_COLOR_HEX["orange"]
    assert color_hex("BLUE") == BAG_COLOR_HEX["navy"]   # case-insensitive alias
    assert color_hex("teal") is None
    assert color_hex(None) is None


# ── stored hexes survive a palette change (ADR-296) ──────────────────────────
#
# `BTRBag.bag_color` is a stored String(10) written at INGEST time, not resolved
# on read. So a hex change silently orphans every row already in the database:
# the bags do not error, they just stop having a colour. This shipped — ADR-296
# moved black #94A3B8 -> #000000 and four already-ingested black totes regrouped
# under "No colour" on the captain's picker.

def test_legacy_hex_still_resolves_to_its_colour():
    """A hex we no longer emit must still name the colour it meant."""
    assert color_name_for_hex("#94A3B8") == "black"      # pre-ADR-296 slate
    assert color_name_for_hex("#94a3b8") == "black"      # case-insensitive


def test_legacy_hex_is_served_as_todays_value():
    """Old and new rows must paint IDENTICALLY — one physical colour, one hex.

    Serving the raw stored value would render pre-ADR-296 black totes slate and
    post-ADR-296 ones true black on the same screen, inventing a colour
    distinction that does not exist on the truck.
    """
    assert canonical_hex("#94A3B8") == "#000000"
    assert canonical_hex("#000000") == "#000000"


def test_current_hexes_are_unchanged_by_canonicalisation():
    for name, hexv in BAG_COLOR_HEX.items():
        assert canonical_hex(hexv) == hexv, name
        assert color_name_for_hex(hexv) == name


def test_unknown_and_absent_stay_none():
    """None is a real answer — the client renders a neutral pill."""
    for v in (None, "", "#ABCDEF", "not a hex"):
        assert canonical_hex(v) is None
        assert color_name_for_hex(v) is None


def test_every_legacy_hex_names_a_colour_that_still_exists():
    """Guards the legacy map itself: a typo'd or retired name would return a
    hex of None and reintroduce the bug it exists to prevent."""
    for hexv, name in _LEGACY_HEX_TO_NAME.items():
        assert name in BAG_COLOR_HEX, f"{hexv} maps to unknown colour {name!r}"
        assert canonical_hex(hexv) == BAG_COLOR_HEX[name]
