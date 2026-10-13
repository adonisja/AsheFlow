"""Re-derive `building_profiles.block_key` changed by ADR-497 D2's noise-pattern fix.

WHY THIS EXISTS
---------------
`derive_block_key` cut an address at the first unit/floor word, including the
street NAME in `55 Front St`, `10 Ground Rd`, `12 Rear Ave`. Those addresses were
unparseable, so a building profile created for one was stored with
`block_key = ""` (ADR-497 D3: the create path now stores "" instead of raising).

ADR-497 D2 made a noise word followed by a street type a street name. Rows
written before it keep what the old pattern gave them, which is one of two things:

    "" (empty)            `55 Front St`       -> unparseable under the old rule
    a TRUNCATED key       `455 Main Front St` -> `455 Main` -> Main_400
                          (correct: Main_Front_St_400)

The second case was found by fuzzing old vs new over 1.38M generated addresses
AFTER the ADR first claimed only empty keys could change: ~94k changed key,
every one from truncated to full, none from parseable to unparseable.

WHAT IT CHANGES, AND WHAT IT CANNOT
-----------------------------------
A row is rewritten only when its stored key is EXACTLY what the old pattern
derives (empty when the old rule could not parse it) AND the new pattern derives
something different. A key that came from anywhere else (GeoClient via the
resolver, a captain's stop, a later fix) does not equal the old derivation and
is left alone.

SAFETY
------
- Dry run by default: prints a count and the per-company tally. `--apply` writes.
- Prints no addresses (CLAUDE.md Dimension 7): a count per company, not a list.
- Idempotent: a second run finds nothing.
- Reads only the database `DATABASE_URL` points at.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys


# The pattern BEFORE ADR-497 D2, kept here only to recognise keys it produced.
OLD_NOISE_PATTERN = (
    r"\b(Attn|Attention|APT|Unit|Ground|Floor|Fl|Host|Suite|Ste|Basement|Bsmt|Lobby|Rear|Front)\b"
)


def rederive(db) -> collections.Counter:
    """Rewrite each key the OLD pattern produced and the new one changes.
    Returns a per-company count. Does not commit."""
    import app.services.derive_block_key as D
    from app.models.building_profile import BuildingProfile

    def key(address: str, pattern: str) -> str:
        saved = D._NOISE_PATTERN
        D._NOISE_PATTERN = pattern
        try:
            parsed = D.derive_block_key(address, tba="")
        finally:
            D._NOISE_PATTERN = saved
        return parsed.block_key if isinstance(parsed, D.ParsedBlock) else ""

    filled: collections.Counter = collections.Counter()
    for p in db.query(BuildingProfile).all():
        old = key(p.normalised_address, OLD_NOISE_PATTERN)
        new = key(p.normalised_address, D._NOISE_PATTERN)
        if (p.block_key or "") == old and new and new != old:
            p.block_key = new
            filled[str(p.company_id)] += 1
    return filled


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the keys (default: dry run)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        filled = rederive(db)
        print(f"re-derived: {sum(filled.values())}")
        for company, n in sorted(filled.items()):
            print(f"  company {company}: {n}")
        if args.apply:
            db.commit()
            print("applied")
        else:
            db.rollback()
            print("dry run: nothing written (pass --apply to write)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
