"""Every super-admin config field can explain itself (ADR-462).

The page edits 49 fields, several of them the most obscure settings in the
product. It had no help affordance at all, and its `hint` strings render ONLY
while `editing` -- so in read mode, the default, it was 49 bare numbers.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
PAGE = ROOT / "frontend/src/pages/superadmin/CompanyDetail.tsx"
DRAWER = ROOT / "frontend/src/components/ui/SettingsHelpDrawer.tsx"


def _page_field_keys() -> list[str]:
    return sorted(set(re.findall(r"key: '([a-z_0-9]+)'", PAGE.read_text())))


def _drawer_entries() -> set[str]:
    return set(re.findall(r"^  ([a-z_][a-z0-9_]*): \{$", DRAWER.read_text(), re.M))


def test_every_field_resolves_to_drawer_content():
    """A key with no entry renders an EMPTY drawer, not an error.

    TypeScript cannot see this: fieldKey is `string | null`, so any string
    type-checks and the failure is a blank panel that reads as broken.
    """
    missing = [k for k in _page_field_keys() if k not in _drawer_entries()]
    assert not missing, f"{len(missing)} field(s) would open an empty drawer: {missing}"


def test_the_page_wires_the_drawer():
    src = PAGE.read_text()
    assert "SettingsHelpDrawer" in src, "the drawer is not mounted"
    assert "setHelpKey(String(f.key))" in src, (
        "the trigger does not pass the field key, so it cannot resolve content"
    )


def test_the_trigger_and_the_drawer_share_a_component():
    """State, trigger and mount must be in one component or the panel never
    opens -- a mistake made once during this change, with a clean build."""
    src = PAGE.read_text().splitlines()

    def owner(needle: str) -> str:
        i = next(n for n, l in enumerate(src) if needle in l)
        for m in range(i, -1, -1):
            match = re.match(r"^(?:export default )?function (\w+)", src[m])
            if match:
                return match.group(1)
        return "<module>"

    owners = {owner("const [helpKey"), owner("setHelpKey(String(f.key))"),
              owner("<SettingsHelpDrawer")}
    assert len(owners) == 1, f"help state/trigger/mount are split across {owners}"


def test_every_dispatch_target_explains_its_unit():
    """The obvious misreading is "how often this crew rides together".

    Each target entry says "per candidate, per truck" so an operator does not
    set 0.80 and conclude the system is broken when the measured share is
    lower.
    """
    src = DRAWER.read_text()
    for key in (k for k in _drawer_entries() if k.startswith("dispatch_target_")):
        i = src.index(f"  {key}: {{")
        block = src[i:src.index("\n  },", i)]
        assert "per candidate, per truck" in block, (
            f"{key} does not state the unit its number is in"
        )


def test_help_titles_match_the_field_labels():
    """A reader should see the same name in the field and in the drawer."""
    page = PAGE.read_text()
    drawer = DRAWER.read_text()
    for key in ("sort_w_dense", "sort_w_doorman", "route_assembly_mode"):
        label = re.search(rf"key: '{key}',\s*label: '([^']+)'", page).group(1)
        i = drawer.index(f"  {key}: {{")
        title = re.search(r"title: '([^']+)'", drawer[i:i + 400]).group(1)
        assert title == label, f"{key}: drawer says {title!r}, field says {label!r}"
