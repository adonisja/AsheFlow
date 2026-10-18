"""A portalled menu must count its own panel as inside (ADR-531).

Found walking the ADR-530 invite path in the browser: Role -> Admin, and the
Confirm Invite summary said Driver. SelectMenu's outside-click test checked only
the trigger wrapper; a portalled panel lives in document.body, so pressing an
option closed the list on mousedown and onChange never ran. Every portalled
menu kept its old value from 2026-09-30 (ADR-484 D3) until this.

Source-inspecting: there is no frontend test runner. The behaviour was proved in
the browser (journal) -- these pin the shape so it cannot quietly regress.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
MENU = SRC / "components" / "ui" / "SelectMenu.tsx"


def _on_down() -> str:
    s = MENU.read_text()
    i = s.index("const onDown = (e: MouseEvent) => {")
    return s[i:s.index("};", i)]


def test_outside_click_checks_the_panel_as_well_as_the_trigger():
    body = _on_down()
    assert "panelRef.current" in body, (
        "SelectMenu's outside-click handler ignores the panel -- a portalled "
        "panel is outside the trigger, so every option press closes the list "
        "before onChange runs (ADR-531)")
    assert "ref.current" in body


def test_the_panel_carries_the_ref():
    """A panelRef nothing is attached to is always null: the check above would
    pass while the bug stayed."""
    s = MENU.read_text()
    i = s.index('role="listbox"')
    opening = s[s.rindex("<div", 0, i):i]
    assert "ref={panelRef}" in opening


def test_the_same_panel_is_used_in_both_modes():
    """One panel element, portalled or not, so the ref covers both."""
    assert "createPortal(panel, document.body) : panel" in MENU.read_text()


# ── D3: SelectMenu draws its own arrow; an overlay one is a duplicate ───────

OVERLAY = re.compile(r"<ChevronDown\b[^>]*(absolute|pointer-events-none)")


def _overlay_chevrons_after_select_menus():
    """Every overlay ChevronDown within 4 lines after a SelectMenu closes."""
    hits = []
    for f in SRC.rglob("*.tsx"):
        if f == MENU:
            continue
        lines = f.read_text().splitlines()
        for i, line in enumerate(lines):
            if "<SelectMenu" not in line:
                continue
            j = i
            while j < len(lines) and "/>" not in lines[j]:
                j += 1
            for k in range(j + 1, min(j + 5, len(lines))):
                if OVERLAY.search(lines[k]):
                    hits.append(f"{f.relative_to(ROOT)}:{k + 1}")
    return hits


def test_no_duplicate_arrow_beside_a_select_menu():
    hits = _overlay_chevrons_after_select_menus()
    assert not hits, (
        "an overlay ChevronDown is drawn beside a SelectMenu, which draws its "
        "own -- users see two arrows (ADR-531 D2): " + ", ".join(hits))


def test_the_gate_recognises_the_shape_it_bans():
    """Guard against a gate that can never fire (the regex drifting)."""
    sample = ('<ChevronDown className="absolute right-2.5 top-1/2 '
              '-translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />')
    assert OVERLAY.search(sample)
    toggle = '<ChevronDown className={`w-3.5 h-3.5 transition-transform`} />'
    assert not OVERLAY.search(toggle), "a toggle's own arrow is not a duplicate"
