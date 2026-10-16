"""ADR-523: pages do not set their own width; the layout does.

Seven pages wrapped themselves in `max-w-{4..7}xl mx-auto` inside the shell, so
on a large monitor they stopped at 896-1280px while the shell grew, and each
navigation jumped the measure. The width comes from Layout's route map
(`layout-wide` / `layout-form`) and the shared `--shell-max`.

`max-w-2xl` / `max-w-3xl` are not caught: those cap a READING measure (a quiz
question, a role description), which is what `max-w-prose` is for, not the
page.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGES = ROOT / "frontend" / "src" / "pages"
CAP = re.compile(r'className="[^"]*(max-w-[4-7]xl[^"]*mx-auto|mx-auto[^"]*max-w-[4-7]xl)')


def test_no_page_caps_its_own_width():
    hits = [
        f"{f.relative_to(ROOT)}:{n}: {line.strip()[:90]}"
        for f in PAGES.rglob("*.tsx")
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if CAP.search(line)
    ]
    assert not hits, (
        "A page sets its own width (ADR-523). Drop the max-w/mx-auto wrapper; "
        "Layout's route map picks layout-wide or layout-form:\n  " + "\n  ".join(hits)
    )


def test_chrome_uses_the_one_shell():
    # The navbar padded INSIDE a max-w-7xl box while main padded outside it:
    # the edges disagreed by 32px. Chrome containers use .layout-shell.
    for rel in ("frontend/src/components/layout/Navbar.tsx",
                "frontend/src/components/layout/SuperAdminLayout.tsx"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "max-w-7xl" not in src, f"{rel} sizes itself; use .layout-shell (ADR-523)"
        assert "layout-shell" in src, rel
