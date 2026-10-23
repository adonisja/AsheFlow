"""The Android app carries the AsheFlow mark: notification and launcher icons (ADR-570).

A push showed a grey square: Firebase had no small icon, fell back to the
launcher icon (React Native's default robot, an opaque square), and Android
draws a small icon from its alpha channel only. Everything here is read from
the files themselves.
"""
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RES = _ROOT / "mobile" / "android" / "app" / "src" / "main" / "res"
_MANIFEST = _ROOT / "mobile" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
_FIREBASE = _ROOT / "mobile" / "firebase.json"
sys.path.insert(0, str(_ROOT / "design"))
import build_brand_assets as B  # noqa: E402

# sha256[:16] of every mipmap PNG React Native generated (git, before ADR-570).
_DEFAULT_ROBOT = {
    "21304a0c9b00da6a", "2846e1a703e51979", "363a569beb72e8b0", "520d05f978a15ba0", "5bacd97a1b41e441",
    "9ff27328b6916b7f", "ded7aabf6a56b694", "e77c5045bfdb6f4b", "eb3a34b13632e0cb", "eef20f25fb1477d8",
}
_SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", head[16:24])


class TestTheNotificationIcon:
    def test_the_manifest_names_a_drawable_that_exists(self):
        m = re.search(r'default_notification_icon"\s+android:resource="@drawable/(\w+)"', _MANIFEST.read_text())
        assert m, "no default_notification_icon: Firebase falls back to the launcher icon (a grey square)"
        assert (_RES / "drawable" / f"{m.group(1)}.xml").exists()

    def test_it_is_a_one_colour_silhouette(self):
        """Android uses only the alpha channel; any other colour is a lie the
        designer will believe."""
        xml = (_RES / "drawable" / "ic_notification.xml").read_text()
        colours = set(re.findall(r'android:(?:fill|stroke)Color="(#\w+)"', xml))
        assert colours == {"#FFFFFFFF"}
        assert 'android:width="24dp"' in xml

    def test_the_core_is_cut_out_not_painted(self):
        """A white core on a white block vanishes in a silhouette."""
        assert 'android:fillType="evenOdd"' in (_RES / "drawable" / "ic_notification.xml").read_text()

    def test_the_accent_colour_is_set_where_firebase_reads_it(self):
        colour = json.loads(_FIREBASE.read_text())["react-native"]["messaging_android_notification_color"]
        name = colour.removeprefix("@color/")
        assert f'<color name="{name}">' in (_RES / "values" / "brand_colors.xml").read_text()
        assert "default_notification_color" not in _MANIFEST.read_text(), \
            "the Firebase library declares that meta-data; declaring it again clashes at merge"


class TestTheLauncherIcon:
    def test_adaptive_icons_have_all_three_layers(self):
        for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
            xml = (_RES / "mipmap-anydpi-v26" / name).read_text()
            for layer in ("background", "foreground", "monochrome"):
                assert f"<{layer} " in xml, f"{name} lacks its {layer} layer"

    def test_the_foreground_stays_inside_the_safe_zone(self):
        """Launcher masks never clip the central 66 dp of a 108 dp layer."""
        xml = (_RES / "drawable" / "ic_launcher_foreground.xml").read_text()
        g = {k: float(v) for k, v in re.findall(r'android:(translateX|translateY|scaleX)="([\d.-]+)"', xml)}
        left, right = g["translateX"] + 2.8 * g["scaleX"], g["translateX"] + 42.3 * g["scaleX"]
        top, bottom = g["translateY"] + 10.8 * g["scaleX"], g["translateY"] + 37.2 * g["scaleX"]
        assert 21 <= left and right <= 87 and 21 <= top and bottom <= 87, (left, right, top, bottom)

    def test_legacy_pngs_exist_at_every_density_and_none_is_the_robot(self):
        for density, px in _SIZES.items():
            for name in ("ic_launcher.png", "ic_launcher_round.png"):
                path = _RES / f"mipmap-{density}" / name
                assert _png_size(path) == (px, px), path
                assert hashlib.sha256(path.read_bytes()).hexdigest()[:16] not in _DEFAULT_ROBOT, \
                    f"{path} is still React Native's default robot"

    def test_the_manifest_uses_the_mipmaps(self):
        text = _MANIFEST.read_text()
        assert 'android:icon="@mipmap/ic_launcher"' in text and 'android:roundIcon="@mipmap/ic_launcher_round"' in text


class TestOneSource:
    def test_the_generated_android_files_match_the_palette(self):
        """The CI design job runs --check; this pins the Android part from the
        backend suite too, so a hand edit to a generated file fails here."""
        spec = json.loads(B.SPEC.read_text())
        stale = [str(p.relative_to(_ROOT)) for p, c in B.build_android(spec).items()
                 if not p.exists() or p.read_text() != c]
        assert not stale, f"run python3 design/build_brand_assets.py: {stale}"

    def test_the_android_geometry_is_the_web_mark(self):
        """The vector restates _mark_paths' numbers; they must not drift."""
        web = B._mark_paths("S", "B", "D")
        for (x1, y1), (x2, y2) in B._LINES_IN + [B._LINE_OUT]:
            assert f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"' in web
        for x, y in B._DOTS:
            assert f'cx="{x}" cy="{y}"' in web
        for x, y, w, h, r in (B._BLOCK, B._CORE):
            assert f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{r:g}"' in web
