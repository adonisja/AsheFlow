#!/usr/bin/env python3
"""Fail when an ungated mobile tab can reach a full-mode-only endpoint.

WHY THIS EXISTS
---------------
ADR-289 gates package-coupled routers behind `operating_mode` — in workforce
mode they return 404. A tab that renders fine but whose buttons all 404 is worse
than a missing tab: the walker taps "Start Route" and nothing happens, or a panel
renders empty because the call was written `.catch(() => null)`.

Three of these shipped before anyone noticed, and all three were found by a human
using the app rather than by a test:

  * the Walker tab      rendered full mode's stop screen in workforce mode
  * AnchorPoints        "I've arrived" 404'd  (ADR-306)
  * FieldOps            six calls, several failing silently (ADR-307)

An earlier hand audit checked each tab COMPONENT and passed AnchorPoints clean,
because `AnchorPointTab` itself calls nothing — the call is one level down in
`TodayAssignmentScreen`. One level deep is not an audit, which is the whole
reason this walks the import tree.

WHAT IT DOES
------------
1. Reads `main.py` for routers registered with `_full_mode`, and resolves each
   one's URL prefix. Nothing is hardcoded: add a router to the gate and this
   picks it up.
2. Walks every nav entry's transitive import tree in `mobile/src`.
3. Fails when a tab with no `feature:` gate reaches one of those prefixes.

THE BARREL TRAP
---------------
`navigation/index.tsx` re-exports every screen, so following it makes EVERY tab
look like it reaches everything. The first run of this logic reported Notifications
as touching /rts and /packages for exactly that reason. It is skipped: it is a
barrel, not a dependency.

Exit 1 on any finding. Run from the repo root.
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOBILE = os.path.join(REPO, "mobile", "src")
MAIN_PY = os.path.join(REPO, "backend", "app", "main.py")

# navigation/index re-exports every screen — a barrel, not a dependency.
SKIP_FILES = {"navigation/index.tsx"}

ALIASES = {
    "@screens/": "screens/",
    "@components/": "components/",
    "@hooks/": "hooks/",
    "@api/": "api/",
    "@contexts/": "contexts/",
    "@theme/": "theme/",
    "@navigation/": "navigation/",
}

IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
URL_RE = re.compile(r"""['"`](/[a-z][a-z0-9\-/]*)""")
TAB_RE = re.compile(r"\{\s*key:\s*'(\w+)',[^}]*?component:\s*(\w+)[^}]*?\}", re.S)
FEATURE_RE = re.compile(r"feature:\s*'(\w+)'")

# KNOWN, ACCEPTED, AND SCHEDULED — not "ignore these".
#
# Both are real defects with an ADR each, and both are being fixed. They are
# listed so the check can go green on everything ELSE today rather than sitting
# disabled until they land — a check nobody has turned on catches nothing.
#
# A NEW finding on either tab still fails: the entry is (tab, url-prefix), so
# adding a different gated call to FieldOps is not covered by this.
#
# Delete each line as its ADR ships. If a line is still here in a month, that is
# the signal it was never scheduled at all.
# Prefixes for routers whose SOURCE is gitignored from the public repo. Kept in
# step with each router's own APIRouter(prefix=...) — a mismatch means this check
# looks at the wrong URLs, so both are asserted by tests/test_mode_gated_tabs.py.
PRIVATE_ROUTER_PREFIXES: dict[str, str] = {
    "walker_routes": "/walker-routes",
    "rts": "/rts",
}

BASELINE: set[tuple[str, str]] = {
    ("AnchorPoints", "/walker-routes/ap-arrival"),   # ADR-306 — endpoint moves to roll_call
    ("FieldOps", "/sort/"),                          # ADR-307 D1 — swap to /btr-sheets
    ("FieldOps", "/rts/summary/"),                   # ADR-307 D1 — swap to /workforce/day-totals
    ("FieldOps", "/rts/handoff/"),                   # ADR-307 D2 — no counterpart; say so
    ("FieldOps", "/walker-routes/"),                 # ADR-307 D1 — swap to /workforce/routes
}


def full_mode_prefixes() -> list[str]:
    """URL prefixes of every router registered under `_full_mode`.

    Read from main.py and the routers themselves rather than hardcoded, so a
    router added to the gate is covered without touching this script.
    """
    src = open(MAIN_PY).read()
    names = [
        m.group(1)
        for m in re.finditer(
            r"include_router\(\s*(\w+)\.router,\s*dependencies=_full_mode", src
        )
    ]
    prefixes = []
    missing = []
    for name in names:
        router_src = os.path.join(REPO, "backend", "app", "routers", f"{name}.py")
        if not os.path.exists(router_src):
            missing.append(name)
            continue
        m = re.search(r"""APIRouter\([^)]*prefix\s*=\s*["']([^"']+)""", open(router_src).read())
        if m:
            prefixes.append(m.group(1))

    # `walker_routes.py` and `rts.py` are PROPRIETARY — gitignored from the public
    # repo — so in public CI their files are absent and their prefixes cannot be
    # read from source. Falling back to a hardcoded map is not a shortcut here: it
    # is the difference between checking and silently checking less.
    #
    # Without it the script drops /rts and /walker-routes, finds fewer hits than
    # it should, and then reports its OWN baseline as stale — a check narrowing
    # its scope while claiming to pass. Verified by hiding both files locally.
    for name in missing:
        fallback = PRIVATE_ROUTER_PREFIXES.get(name)
        if fallback:
            prefixes.append(fallback)
        else:
            # An unknown private router is a real gap: fail loudly rather than
            # check a subset and report OK.
            print(
                f"ERROR: {name}.router is registered _full_mode but its source is "
                f"absent and it has no entry in PRIVATE_ROUTER_PREFIXES. Add one — "
                f"otherwise this check silently stops covering it.",
                file=sys.stderr,
            )
            return []
    return sorted(prefixes)


def resolve(spec: str, from_file: str) -> str | None:
    """Map an import specifier to a file under mobile/src, or None if external."""
    for alias, real in ALIASES.items():
        if spec.startswith(alias):
            spec = real + spec[len(alias):]
            break
    else:
        if not spec.startswith("."):
            return None                       # node_modules
        spec = os.path.normpath(os.path.join(os.path.dirname(from_file), spec))

    for ext in (".tsx", ".ts", "/index.tsx", "/index.ts"):
        if os.path.exists(os.path.join(MOBILE, spec + ext)):
            return spec + ext
    return None


def reachable_urls(rel_path: str, prefixes: list[str],
                   seen: set[str] | None = None) -> dict[str, str]:
    """{url: file that calls it} for every gated URL reachable from this file."""
    seen = seen if seen is not None else set()
    if rel_path in seen or rel_path in SKIP_FILES:
        return {}
    full = os.path.join(MOBILE, rel_path)
    if not os.path.exists(full):
        return {}
    seen.add(rel_path)

    src = open(full, encoding="utf-8").read()
    found = {
        url: rel_path
        for url in URL_RE.findall(src)
        if any(url == p or url.startswith(p + "/") for p in prefixes)
    }
    for spec in IMPORT_RE.findall(src):
        child = resolve(spec, rel_path)
        if child:
            found.update(reachable_urls(child, prefixes, seen))
    return found


def main() -> int:
    prefixes = full_mode_prefixes()
    if not prefixes:
        print("could not read any _full_mode router prefixes from main.py", file=sys.stderr)
        return 1

    nav_rel = "navigation/index.tsx"
    nav = open(os.path.join(MOBILE, nav_rel), encoding="utf-8").read()

    # component name -> file, from the nav file's own imports
    components: dict[str, str] = {}
    for m in re.finditer(r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]""", nav):
        path = resolve(m.group(2), nav_rel)
        if path:
            components[m.group(1)] = path

    findings: list[tuple[str, str, str]] = []
    baselined: list[tuple[str, str, str]] = []
    for m in TAB_RE.finditer(nav):
        key, comp = m.group(1), m.group(2)
        if FEATURE_RE.search(m.group(0)):
            continue                          # gated — the point of the check
        path = components.get(comp)
        if not path:
            continue
        for url, caller in sorted(reachable_urls(path, prefixes).items()):
            if (key, url) in BASELINE:
                baselined.append((key, url, caller))
                continue
            findings.append((key, url, caller))

    print(f"full-mode prefixes: {', '.join(prefixes)}")
    print(f"checked {len(TAB_RE.findall(nav))} tabs\n")

    if baselined:
        print(f"{len(baselined)} known finding(s), each with an ADR in flight:")
        for key, url, _ in baselined:
            print(f"    {key}  {url}")
        print()

    # A baseline entry that no longer fires is a fix that landed — say so, so the
    # line gets deleted rather than quietly protecting nothing.
    stale = BASELINE - {(k, u) for k, u, _ in baselined}
    if stale:
        print("These BASELINE entries no longer fire — delete them:")
        for key, url in sorted(stale):
            print(f"    ({key!r}, {url!r})")
        print()

    if not findings:
        print("OK — no NEW ungated tab reaches a full-mode endpoint.")
        return 0

    print("FAIL — ungated tabs reach full-mode-only endpoints.\n")
    print("In workforce mode these 404. Either gate the tab with `feature:`,")
    print("gate the section inside it, or swap the call for its workforce")
    print("counterpart (ADR-307 D1).\n")
    width = max(len(k) for k, _, _ in findings)
    for key, url, caller in findings:
        print(f"  {key:<{width}}  {url:<30} called from {caller}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
