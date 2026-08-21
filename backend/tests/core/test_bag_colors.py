"""bag_colors — parse the physical bag color from a manifest label (ADR-230).
Public module (no proprietary imports), so this test runs in public CI."""
from app.core.bag_colors import parse_bag_label, color_hex, BAG_COLOR_HEX


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
