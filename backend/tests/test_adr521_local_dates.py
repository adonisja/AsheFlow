"""ADR-521: a day a person sees is their local day.

`new Date().toISOString().slice(0, 10)` and `ts.split('T')[0]` give the UTC
day, so from 8 PM Eastern they read TOMORROW: an incident filed on the 15th
listed as the 16th, an assignment-change request filed for the wrong day. The
rule sat in LEARNING_GUIDE twice and the idiom came back anyway, so it is a
test now. Use `localYMD()` / `localDayOf()` (mobile `hooks/localDate.ts`) or
`getLocalYMD()` (web `utils/date.ts`), or a record's own `date` field.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "mobile" / "src", ROOT / "frontend" / "src"]

# "today" in UTC, and the UTC day of a timestamp field (`created_at`, ...).
PATTERNS = [
    re.compile(r"toISOString\(\)\s*\.\s*slice\(\s*0\s*,\s*10\s*\)"),
    re.compile(r"toISOString\(\)\s*\.\s*split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\]"),
    re.compile(r"\w+_at\??\s*\.\s*split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\]"),
    re.compile(r"\w+_at\??\s*\.\s*slice\(\s*0\s*,\s*10\s*\)"),
]

# path (relative to repo root) -> why the UTC day is right there.
ALLOWED = {
    "frontend/src/pages/superadmin/CollectionData.tsx":
        "download filename stamp; nobody reads it as their day",
}


def _hits():
    for base in SOURCES:
        for f in base.rglob("*"):
            if f.suffix not in (".ts", ".tsx") or "__tests__" in f.parts or ".test." in f.name:
                continue
            rel = f.relative_to(ROOT).as_posix()
            if rel in ALLOWED:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("//", "*", "/*")):
                    continue                      # prose ABOUT the idiom
                if any(p.search(line) for p in PATTERNS):
                    yield f"{rel}:{n}: {stripped[:100]}"


def test_no_client_cuts_a_utc_day():
    hits = list(_hits())
    assert not hits, (
        "UTC day where a person sees a day (ADR-521). Use localYMD()/localDayOf() "
        "(mobile) or getLocalYMD() (web), or the record's own date field:\n  "
        + "\n  ".join(hits)
    )


def test_every_allowed_file_still_uses_the_idiom():
    # A stale exemption protects nothing and invites the next one.
    for rel in ALLOWED:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert any(p.search(src) for p in PATTERNS), f"{rel} no longer needs its ADR-521 exemption"
