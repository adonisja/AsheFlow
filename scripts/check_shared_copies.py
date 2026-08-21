#!/usr/bin/env python3
"""Web and mobile copies of shared logic must stay identical.

WHY THIS EXISTS
---------------
ADR-271 B put chart aggregation on the CLIENT, so the logic exists twice — once
in `frontend/`, once in `mobile/`. ADR-275 D1 did the same for notification
classification. Both files carry a docstring saying "a change lands on both
surfaces in the same commit", and both were kept in step by a diff a human had
to remember to run.

That is not a mechanism, and it has already failed. Porting the notification
classifier to mobile, the per-notification-date confirmation fetch was
"simplified" to a single date. The result: "NEEDS YOUR RESPONSE" rendered above
"No assignment today" — an alert telling a walker to act on something that did
not exist. The web version had been correct; the drift was introduced by the
copy.

I deferred building this check three times across two sessions. It is ~60 lines.

WHAT IT CHECKS
--------------
For each registered pair: strip the platform-specific header (a banner comment
and the type-import line, which legitimately differ) and require the remainder
to match byte for byte.

ADDING A PAIR
-------------
Append to PAIRS. If a new file is copied between surfaces and not registered
here, this check cannot see it — so registering it is part of copying it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Pair:
    """One copied file, and the rule for what to ignore at the top of each."""

    def __init__(
        self,
        name: str,
        web: str,
        mobile: str,
        *,
        skip_leading_docstring: bool = True,
        ignore_prefixes: tuple[str, ...] = ("import type",),
    ) -> None:
        self.name = name
        self.web = ROOT / web
        self.mobile = ROOT / mobile
        self.skip_leading_docstring = skip_leading_docstring
        self.ignore_prefixes = ignore_prefixes

    def body(self, path: Path) -> list[str]:
        """The comparable content: no leading banner, no platform import lines.

        The mobile copies carry an extra header explaining that they are ports,
        and their type import points at a different module. Everything after
        that must be identical — that is the whole property.
        """
        lines = path.read_text(encoding="utf-8").splitlines()

        if self.skip_leading_docstring:
            # Drop every leading block comment. Mobile has two (the port banner
            # plus the original docstring); web has one.
            i = 0
            while i < len(lines):
                stripped = lines[i].strip()
                if not stripped:
                    i += 1
                    continue
                if stripped.startswith("/*"):
                    while i < len(lines) and "*/" not in lines[i]:
                        i += 1
                    i += 1
                    continue
                break
            lines = lines[i:]

        return [
            ln for ln in lines
            if ln.strip() and not any(ln.strip().startswith(p) for p in self.ignore_prefixes)
        ]


PAIRS = [
    Pair(
        "stats aggregation (ADR-271 B)",
        "frontend/src/components/stats/aggregate.ts",
        "mobile/src/components/stats/aggregate.ts",
    ),
    Pair(
        "notification classifier (ADR-275 D1)",
        "frontend/src/components/notifications/classify.ts",
        "mobile/src/components/notifications/classify.ts",
    ),
]


# Same basename on both surfaces but NOT a copy — independent implementations
# that happen to share a name. Listed so the unregistered-pair warning below
# stays quiet about them, and so the judgement is recorded rather than re-made.
_KNOWN_NOT_COPIES = {
    "errorText.ts",   # web 54 lines / mobile 29 — different error shapes
    "types.ts",       # web is the full API surface; mobile declares what it reads
}


def _warn_unregistered() -> None:
    """Flag same-named files on both surfaces that nobody has registered.

    The check can only see pairs in PAIRS. A future copied file that is never
    registered is invisible to it — the failure mode where the guard exists and
    protects nothing. This does not fail the build (a shared basename is not
    proof of a copy) but it does put the decision in front of someone.
    """
    web = {p.name for p in (ROOT / "frontend" / "src").rglob("*.ts")
           if not p.name.endswith(".d.ts")}
    mob = {p.name for p in (ROOT / "mobile" / "src").rglob("*.ts")}
    registered = {p.web.name for p in PAIRS} | {p.mobile.name for p in PAIRS}

    unknown = sorted((web & mob) - registered - _KNOWN_NOT_COPIES)
    if unknown:
        print("\n  NOTE — same filename on both surfaces, not registered as a pair:")
        for name in unknown:
            print(f"    {name}")
        print("    If either is a COPY, add it to PAIRS. If not, add it to"
              " _KNOWN_NOT_COPIES.")


def main() -> int:
    failures: list[str] = []
    checked = 0

    for pair in PAIRS:
        for path in (pair.web, pair.mobile):
            if not path.exists():
                failures.append(f"{pair.name}: missing {path.relative_to(ROOT)}")
        if failures:
            continue

        web_body = pair.body(pair.web)
        mob_body = pair.body(pair.mobile)
        checked += 1

        if web_body == mob_body:
            print(f"  OK   {pair.name} ({len(web_body)} lines)")
            continue

        # Report the FIRST divergence with line context — "they differ" sends
        # the reader back to diff by hand, which is the habit this replaces.
        detail = ""
        for n, (w, m) in enumerate(zip(web_body, mob_body), start=1):
            if w != m:
                detail = (
                    f"\n       first difference at comparable line {n}:"
                    f"\n         web:    {w.strip()[:90]}"
                    f"\n         mobile: {m.strip()[:90]}"
                )
                break
        else:
            detail = (
                f"\n       same prefix, different length: "
                f"web={len(web_body)} mobile={len(mob_body)} lines"
            )
        failures.append(f"{pair.name}: copies have DRIFTED{detail}")

    if failures:
        print("\nFAIL — shared logic has diverged between web and mobile:\n")
        for f in failures:
            print(f"  {f}\n")
        print(
            "  These files are copies on purpose (client-side logic, two runtimes).\n"
            "  A change must land on BOTH in the same commit — a divergence means one\n"
            "  surface is now computing something different from the other.\n"
        )
        return 1

    _warn_unregistered()
    print(f"\nOK — {checked} shared copies identical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
