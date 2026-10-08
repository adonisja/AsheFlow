#!/usr/bin/env python3
"""No two scheduled tasks may start in the same minute (ADR-487).

Two tasks firing in the same second contend for the same worker pool for no
reason, and a log read afterwards cannot tell which one was slow. The fix is
always to move one by a minute — never to merge the task bodies, which would
serialise work that currently runs in parallel (ADR-487 D4d).

READS THE SOURCE BY AST, NOT BY IMPORTING THE APP
=================================================

The first version did `from app.celery_app import celery_app` and read
`conf.beat_schedule`. That is the more direct check and it broke CI: this runs in
the **Design tokens** job, which installs no dependencies at all — every other
check there is pure stdlib, which is why that job is fast. `ModuleNotFoundError:
No module named 'celery'`.

Two fixes were possible: install the backend requirements in that job, or stop
needing them. The second is right. A *scheduling* check has no business importing
an application — pulling in Celery, SQLAlchemy and the whole model layer to read
a dict of integers is a dependency this gate should not own, and it would make
the gate fail for reasons unrelated to the schedule (a broken import anywhere in
`app/` would break it).

`beat_schedule` is a literal dict of literal `crontab(...)` calls, so the AST has
everything. The cost is that this cannot see a schedule built dynamically — which
is a real limit, asserted below rather than left implicit: if the entry count
read by AST ever drops well below what the file contains, this gate has gone
blind and says so.

WHY A SCRIPT AND NOT A REVIEW HABIT
===================================

Three collisions existed in `beat_schedule` and had been there long enough to
reach an operator's backlog by hand. Two were obvious on a read; the third was
not, and that is the whole reason for the automated check:

    03:30  expire_owner_email_changes | purge_expired_operational_records [dom=1]

The monthly purge only collides on the 1st of each month, so a daily-only scan
skips it — including the first version of this check, which filtered out every
entry carrying a `day_of_month` or `day_of_week` qualifier and reported two
collisions instead of three. **A collision check that ignores conditional
schedules is the same bug it is looking for.**

THE TENANT-TIME CASE
====================

Everything above is about server-time `crontab` entries. ADR-487 D4d introduces
notices anchored to TENANT config (`shift_end`, `dispatch_confirmation_cutoff`),
whose effective fire time differs per tenant and is not visible in this file at
all. Those cannot be checked statically, so the anchored sweep carries the same
rule at RUNTIME: when two notices resolve to the same minute for one tenant, the
later one is nudged by a minute rather than firing concurrently. This script
checks the static half, `_stagger_within_tenant` checks the dynamic half, and the
rule is stated twice because the two halves cannot be checked by one mechanism.
"""
from __future__ import annotations

import ast
import pathlib
import sys
from collections import defaultdict

CELERY_APP = (
    pathlib.Path(__file__).resolve().parent.parent / "backend" / "app" / "celery_app.py"
)

# Below this, assume the AST walk has gone blind rather than that the schedule
# shrank. The file had 30 entries when this gate was written.
MIN_ENTRIES = 20


def _literal(node: ast.AST) -> object | None:
    """A literal int/str, or None for anything computed."""
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _crontab_fields(call: ast.Call) -> dict[str, object] | None:
    """The keyword fields of a `crontab(...)` call, or None if it is not one."""
    fn = call.func
    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
    if name != "crontab":
        return None
    out: dict[str, object] = {}
    for kw in call.keywords:
        if kw.arg:
            out[kw.arg] = _literal(kw.value)
    return out


def _schedule_entries() -> list[tuple[str, str, dict[str, object]]]:
    """(entry name, task path, crontab fields) for every literal beat entry."""
    tree = ast.parse(CELERY_APP.read_text())
    entries: list[tuple[str, str, dict[str, object]]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Attribute) and t.attr == "beat_schedule"
            for t in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue

        for key, val in zip(node.value.keys, node.value.values):
            name = _literal(key) if key is not None else None
            if not isinstance(name, str) or not isinstance(val, ast.Dict):
                continue
            task = ""
            fields: dict[str, object] | None = None
            for k2, v2 in zip(val.keys, val.values):
                k2v = _literal(k2) if k2 is not None else None
                if k2v == "task":
                    task = str(_literal(v2) or "")
                elif k2v == "schedule" and isinstance(v2, ast.Call):
                    fields = _crontab_fields(v2)
            if fields is not None:
                entries.append((name, task, fields))
    return entries


def main() -> int:
    if not CELERY_APP.exists():
        print(f"FAIL: {CELERY_APP} not found")
        return 1

    entries = _schedule_entries()

    # A walk that finds nothing passes every check below vacuously. This is the
    # same guard the ADR-464 direction lesson asks for: assert the derivation is
    # non-empty, so a refactor that moves the schedule fails here instead of
    # silently reporting success.
    if len(entries) < MIN_ENTRIES:
        print(
            f"FAIL: only {len(entries)} beat entries read by AST (expected "
            f">= {MIN_ENTRIES}).\n\n"
            f"Either the schedule moved out of `celery_app.conf.beat_schedule = "
            f"{{...}}`, or entries are now built dynamically — which this gate "
            f"cannot see. Do not lower MIN_ENTRIES: fix the walk, or check the "
            f"schedule at runtime instead."
        )
        return 1

    # Group by TIME only, then test day-overlap pairwise. An absent day
    # qualifier is a WILDCARD, not a value: `crontab(hour=3, minute=30)` runs
    # every day and therefore overlaps `day_of_month=1`.
    #
    # Keying on str(day_of_month) was wrong and the probe caught it — the daily
    # entry keyed as "None" and the monthly as "1", so they landed in different
    # buckets and the 1st-of-the-month collision this gate was WRITTEN for went
    # undetected. Two implementations of this check have now made the same class
    # of mistake in opposite directions: the first ignored the qualifiers
    # entirely, the second treated absence as a distinct value.
    by_time: dict[tuple[int, int], list[tuple[str, str, object, object]]] = defaultdict(list)
    for name, task, f in entries:
        hour, minute = f.get("hour"), f.get("minute")
        # Only fixed start times contend. `minute="*/10"` is a recurring sweep,
        # not a start, and two of those in the same minute is not this problem.
        if not isinstance(hour, int) or not isinstance(minute, int):
            continue
        by_time[(hour, minute)].append(
            (f"{name}  ({task.split('.')[-1]})", task,
             f.get("day_of_month"), f.get("day_of_week"))
        )

    def _days_overlap(a: object, b: object) -> bool:
        """None is every day, so it overlaps anything. Otherwise equal values do."""
        return a is None or b is None or a == b

    collisions: dict[tuple, list[str]] = {}
    for (hour, minute), group in by_time.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                label_a, _, dom_a, dow_a = group[i]
                label_b, _, dom_b, dow_b = group[j]
                if _days_overlap(dom_a, dom_b) and _days_overlap(dow_a, dow_b):
                    key = (hour, minute, str(dom_a if dom_a is not None else dom_b),
                           str(dow_a if dow_a is not None else dow_b))
                    collisions.setdefault(key, [])
                    for lbl in (label_a, label_b):
                        if lbl not in collisions[key]:
                            collisions[key].append(lbl)

    slots = by_time
    if not collisions:
        print(
            f"OK — {len(entries)} beat entries read, {len(slots)} with a fixed "
            f"start time, no two share a minute"
        )
        return 0

    print("FAIL: scheduled tasks starting in the same minute\n")
    for (hour, minute, dom, dow), names in sorted(collisions.items()):
        qual = ""
        if dom != "None":
            qual += f"  day_of_month={dom}"
        if dow != "None":
            qual += f"  day_of_week={dow}"
        print(f"  {hour:02d}:{minute:02d}{qual}")
        for n in names:
            print(f"      {n}")
        print()
    print("Move one by a minute. Do NOT merge the task bodies — they run in")
    print("parallel today and merging serialises them (ADR-487 D4d).")
    print("Prefer to move the cheaper task: a network-bound batch job keeps its")
    print("slot, a pure-DB sweep is the one to displace.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
