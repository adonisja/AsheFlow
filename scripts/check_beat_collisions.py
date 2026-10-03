#!/usr/bin/env python3
"""No two scheduled tasks may start in the same minute (ADR-487).

Two tasks firing in the same second contend for the same worker pool for no
reason, and a log read afterwards cannot tell which one was slow. The fix is
always to move one by a minute — never to merge the task bodies, which would
serialise work that currently runs in parallel (ADR-487 D4d).

WHY THIS IS A SCRIPT AND NOT A REVIEW HABIT
===========================================

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
later one is nudged by a minute rather than firing concurrently. See
`_stagger_within_tenant` in the notice sweep (NOTICE ADR) — this script checks
the static half, that function checks the dynamic half, and the rule is the same
one stated twice because the two halves cannot be checked by one mechanism.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _single(value) -> str | None:
    """A crontab field that names exactly one value, else None.

    `minute="*/10"` expands to six values and is a recurring sweep, not a start
    time — two of those in the same minute is not the contention this guards.
    """
    try:
        items = sorted(value)
    except TypeError:
        return None
    return str(items[0]) if len(items) == 1 else None


def main() -> int:
    from app.celery_app import celery_app

    slots: dict[tuple, list[str]] = defaultdict(list)
    for name, cfg in celery_app.conf.beat_schedule.items():
        sched = cfg.get("schedule")
        hour = _single(getattr(sched, "hour", None))
        minute = _single(getattr(sched, "minute", None))
        if hour is None or minute is None:
            continue
        # The qualifiers are part of the key, so a monthly task only collides
        # with something that shares its day. Dropping them was the original bug.
        dom = str(sorted(getattr(sched, "day_of_month", []) or []))
        dow = str(sorted(getattr(sched, "day_of_week", []) or []))
        slots[(hour, minute, dom, dow)].append(name)

    collisions = {k: v for k, v in slots.items() if len(v) > 1}
    if not collisions:
        print(f"OK — {len(slots)} fixed-time beat entries, no two share a minute")
        return 0

    print("FAIL: scheduled tasks starting in the same minute\n")
    for (hour, minute, dom, dow), names in sorted(collisions.items()):
        qual = ""
        if dom not in ("[]", "['*']"):
            qual += f"  day_of_month={dom}"
        if dow not in ("[]", "['*']"):
            qual += f"  day_of_week={dow}"
        print(f"  {hour.zfill(2)}:{minute.zfill(2)}{qual}")
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
