"""The iOS app carries the AsheFlow mark: app icon and launch screen (ADR-572).

The icon set held only Contents.json (iOS showed its blank default icon, also on
every notification), and the launch screen was React Native's template
("AsheFlowMobile", "Powered by React Native"). Read with the standard library.
"""
import json
import struct
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_XC = _ROOT / "mobile" / "ios" / "AsheFlowMobile" / "Images.xcassets"
_ICONS = _XC / "AppIcon.appiconset"
_STORYBOARD = _ROOT / "mobile" / "ios" / "AsheFlowMobile" / "LaunchScreen.storyboard"


def _ihdr(path: Path) -> tuple[int, int, int]:
    """(width, height, colour type) from the PNG header."""
    head = path.read_bytes()[:26]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    w, h = struct.unpack(">II", head[16:24])
    return w, h, head[25]


def test_every_icon_slot_has_a_file_at_the_right_size():
    images = json.loads((_ICONS / "Contents.json").read_text())["images"]
    assert len(images) == 9
    for img in images:
        assert "filename" in img, f"empty slot {img}"
        pt = float(img["size"].split("x")[0]); scale = int(img["scale"][0])
        w, h, _ = _ihdr(_ICONS / img["filename"])
        assert (w, h) == (round(pt * scale), round(pt * scale)), img


def test_every_icon_is_opaque():
    """iOS masks the corners itself; the App Store refuses an icon with alpha.
    PNG colour type 2 is RGB; 6 would be RGBA."""
    for img in json.loads((_ICONS / "Contents.json").read_text())["images"]:
        assert _ihdr(_ICONS / img["filename"])[2] == 2, f"{img['filename']} has an alpha channel"


def test_the_launch_screen_shows_the_mark_not_the_template():
    sb = _STORYBOARD.read_text()
    assert "React Native" not in sb and 'text="AsheFlowMobile"' not in sb
    assert 'image="LaunchMark"' in sb and '<image name="LaunchMark"' in sb
    marks = json.loads((_XC / "LaunchMark.imageset" / "Contents.json").read_text())["images"]
    assert {m["scale"] for m in marks} == {"1x", "2x", "3x"}
    for m in marks:
        assert (_XC / "LaunchMark.imageset" / m["filename"]).exists()


def test_the_launch_background_is_the_brand_navy():
    import re, sys
    sys.path.insert(0, str(_ROOT / "design"))
    import build_brand_assets as B
    navy = B.hex_colour(json.loads(B.SPEC.read_text()), "light", "primary")
    r, g, b = (int(navy[i:i + 2], 16) / 255 for i in (1, 3, 5))
    m = re.search(r'<color key="backgroundColor" red="([\d.]+)" green="([\d.]+)" blue="([\d.]+)"',
                  _STORYBOARD.read_text())
    assert m and all(abs(float(v) - c) < 0.001 for v, c in zip(m.groups(), (r, g, b)))
