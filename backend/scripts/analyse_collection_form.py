"""How the address-collection form has been used, to design the next one (ADR-504 D6).

    python3 scripts/analyse_collection_form.py [--company <uuid>] [--min-word 3]

READ-ONLY, and it prints AGGREGATES ONLY: counts, percentages, distributions,
and frequent words. Never an address, a door key, a collector handle, a device id,
a note, or any single row. That is ADR-504 D6's line: the collected data may
shape the FORM; none of it may become a record or leave its tenant as anything
but de-identified statistics.

Free text (the `other` workload answer and the note) is reported as WORD
FREQUENCIES, lower-cased, with digits and street-type words removed, and only
for words used at least `--min-word` times (default 3) across different rows.
A word fewer people used than that is suppressed, because a rare word can
identify the person or the door it came from.

Scope: every row the database holds, or one company's with --company.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_STOP = set("""
a an the and or of to in on at for with by is are was were be it this that there
not no yes very but if as from up down out door doors building buildings floor
""".split())
_STREETISH = re.compile(
    r"^(st|street|ave|avenue|av|blvd|rd|road|pl|place|dr|lane|ln|pkwy|n|s|e|w|"
    r"north|south|east|west|apt|unit|suite|ste)$"
)


def pct(n: int, d: int) -> str:
    return f"{n:>5}  ({(100 * n / d if d else 0):5.1f}%)"


def words(texts: list[str], min_count: int) -> list[tuple[str, int]]:
    """Frequent words, counted once per row so one long note cannot dominate."""
    per_row = collections.Counter()
    for t in texts:
        toks = {
            w for w in re.findall(r"[a-z]+", (t or "").lower())
            if len(w) > 2 and w not in _STOP and not _STREETISH.match(w)
        }
        per_row.update(toks)
    return [(w, n) for w, n in per_row.most_common() if n >= min_count]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", help="restrict to one company's rows")
    ap.add_argument("--min-word", type=int, default=3, help="suppress words used by fewer rows")
    args = ap.parse_args()

    from app.database import SessionLocal
    from app.models.collection import CollectedAddressProfile as C

    db = SessionLocal()
    try:
        q = db.query(C)
        if args.company:
            q = q.filter(C.company_id == args.company)
        rows = q.all()
    finally:
        db.close()

    n = len(rows)
    print(f"rows: {n}   campaigns: {len({r.token_id for r in rows})}")
    if not n:
        return 0

    print("\n── fill rates (how often each field was answered)")
    fields = {
        "building_type (not 'unknown')": lambda r: r.building_type not in (None, "", "unknown"),
        "workloads (any)":               lambda r: bool(r.workloads),
        "workload_other":                lambda r: bool((r.workload_other or "").strip()),
        "has_security_desk = true":      lambda r: bool(r.has_security_desk),
        "opens_at":                      lambda r: r.opens_at is not None,
        "closes_at":                     lambda r: r.closes_at is not None,
        "break_start / break_end":       lambda r: r.break_start is not None or r.break_end is not None,
        "troublesome = true":            lambda r: bool(r.troublesome),
        "note":                          lambda r: bool((r.note or "").strip()),
        "collected_by (handle)":         lambda r: bool((r.collected_by or "").strip()),
        "address_flag set (ADR-496)":    lambda r: bool(getattr(r, "address_flag", None)),
    }
    for label, f in fields.items():
        print(f"  {label:<32} {pct(sum(1 for r in rows if f(r)), n)}")

    print("\n── building category / type")
    for k, v in collections.Counter(r.building_category or "unset" for r in rows).most_common():
        print(f"  category {k:<22} {pct(v, n)}")
    for k, v in collections.Counter(r.building_type or "unset" for r in rows).most_common():
        print(f"  type     {k:<22} {pct(v, n)}")

    print("\n── workloads (a row may hold several)")
    tags = collections.Counter(t for r in rows for t in (r.workloads or []))
    for k, v in tags.most_common():
        print(f"  {k:<30} {pct(v, n)}")
    sizes = collections.Counter(len(r.workloads or []) for r in rows)
    print("  tags per row: " + ", ".join(f"{k}→{v}" for k, v in sorted(sizes.items())))
    pairs = collections.Counter()
    for r in rows:
        ts = sorted(set(r.workloads or []))
        pairs.update((a, b) for i, a in enumerate(ts) for b in ts[i + 1:])
    if pairs:
        print("  most common pairs: " + "; ".join(f"{a}+{b} {c}" for (a, b), c in pairs.most_common(6)))

    print("\n── doors observed twice (ADR-420): where collectors disagreed")
    by_door = collections.defaultdict(list)
    for r in rows:
        by_door[(r.token_id, r.door_key)].append(r)
    twice = [v for v in by_door.values() if len(v) >= 2]
    disagree = [v for v in twice if len({x.building_type for x in v}) > 1]
    print(f"  doors with 2+ observations {len(twice)}; disagreeing on type {len(disagree)}")
    confused = collections.Counter(tuple(sorted({x.building_type for x in v})) for v in disagree)
    for types, c in confused.most_common(8):
        print(f"    {' vs '.join(types):<40} {c}")
    wl_disagree = sum(1 for v in twice if len({tuple(sorted(x.workloads or [])) for x in v}) > 1)
    print(f"  doors whose workload tags differ between observations: {wl_disagree}")

    print("\n── hours given")
    spans = [
        (r.closes_at.hour * 60 + r.closes_at.minute) - (r.opens_at.hour * 60 + r.opens_at.minute)
        for r in rows if r.opens_at and r.closes_at
    ]
    if spans:
        print(f"  rows with both open and close: {len(spans)}; "
              f"median span {statistics.median(spans) / 60:.1f} h; "
              f"close before open (likely an input error): {sum(1 for s in spans if s <= 0)}")

    print("\n── note length (characters, rows with a note)")
    lens = [len(r.note.strip()) for r in rows if (r.note or "").strip()]
    if lens:
        print(f"  median {statistics.median(lens):.0f}; 90th pct "
              f"{sorted(lens)[int(0.9 * (len(lens) - 1))]}; max {max(lens)}")

    for label, texts in (("'other' workload answers", [r.workload_other for r in rows if r.workload_other]),
                         ("notes", [r.note for r in rows if r.note])):
        common = words(texts, args.min_word)
        print(f"\n── frequent words in {label} (used by ≥{args.min_word} rows; rarer words suppressed)")
        print("  " + (", ".join(f"{w} {c}" for w, c in common[:40]) or "(none above the threshold)"))

    print("\n── collection dates")
    days = collections.Counter(r.collected_on.isoformat() for r in rows if r.collected_on)
    print(f"  distinct days {len(days)}; busiest day {max(days.values()) if days else 0} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
