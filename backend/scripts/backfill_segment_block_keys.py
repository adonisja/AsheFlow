"""Fill `StreetSegment.block_key` for connector segments (ADR-408 D3b).

WHY THIS EXISTS
---------------
Segment adjacency is derived from shared LION nodes, but the graph the sort
traverses is keyed on `block_key`. A node-sharing pair only becomes an edge when
BOTH segments have one — and measured on staging, only 13.4% of pairs did.

The cause is two populations that never meet:

    source=package_address   block_key, no street_name   (357 rows locally)
    source=connector_walk    street_name, no block_key   (222 rows locally)
    both                     0

Rows resolved from a delivered address got a block key; rows discovered by
walking the graph got a street name. At a four-way intersection the crossing
segments are the connectors — so the pairs that make an intersection an
intersection are exactly the pairs that cannot project onto the graph.

HOW A MISSING KEY IS DERIVED
----------------------------
`derive_block_key` needs a house number as its first token, and these rows have
none. The NEIGHBOURS supply what the address cannot:

    10 AVENUE (segment 0227819)
      node 0021133 -> W_23_St_400, W_23_St_500   => cross street W_23_St
      node 0021134 -> W_24_St_400, W_24_St_500   => cross street W_24_St
      => "10_Avenue_btw_W_23_St_W_24_St"

Measured: 222 of 222 derivable, 0 ambiguous. Every connector segment has an
unambiguous single cross street at BOTH endpoints, which is what an avenue
segment between two numbered streets looks like.

The synthesised key takes a DISTINCT shape — `{Street}_btw_{lo}_{hi}` — rather
than imitating `{street}_{type}_{hundred}`. A hundred-block key asserts a
house-number range; this asserts a span between two crossings. Making them look
alike would let a later reader parse a synthesised key for a hundred nobody
measured.

SAFETY
------
- Writes ONLY where `block_key IS NULL`. Never overwrites a derived key.
- Idempotent: a second run is a no-op, a partial run resumes.
- Reads only the database it is pointed at, so running it against production
  produces production's answer. Nothing is copied between environments.
- `--dry-run` reports without writing.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys


def _cross_street(block_keys: set[str]) -> str | None:
    """The street part shared by every block key at a node, or None.

    `{'W_24_St_400', 'W_24_St_500'}` -> `'W_24_St'`: both sides of one crossing.
    Two DIFFERENT streets at a node means the neighbours disagree about where
    this endpoint is, and an ambiguous endpoint must not produce a confident
    key — better a null than a plausible wrong span.
    """
    streets = {k.rsplit("_", 1)[0] for k in block_keys if k}
    return streets.pop() if len(streets) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    import psycopg2
    conn = psycopg2.connect(url)
    cur = conn.cursor()

    cur.execute(
        "SELECT segment_id, from_lion_node_id, to_lion_node_id, block_key, street_name "
        "FROM street_segments WHERE from_lion_node_id IS NOT NULL "
        "AND to_lion_node_id IS NOT NULL"
    )
    rows = cur.fetchall()

    by_node: dict[str, list] = collections.defaultdict(list)
    for row in rows:
        by_node[row[1]].append(row)
        by_node[row[2]].append(row)

    filled: list[tuple[str, str]] = []
    skipped_ambiguous = 0
    skipped_no_name = 0

    for seg_id, node_a, node_b, block_key, street_name in rows:
        if block_key:
            continue                      # already keyed; never overwritten
        if not street_name:
            skipped_no_name += 1
            continue

        lo = _cross_street({r[3] for r in by_node[node_a] if r[3]})
        hi = _cross_street({r[3] for r in by_node[node_b] if r[3]})
        if not lo or not hi or lo == hi:
            # No unambiguous crossing at one end, or a loop. Leave it null:
            # a segment with no key contributes no edge, which is the current
            # behaviour and strictly better than a guessed one.
            skipped_ambiguous += 1
            continue

        street = "_".join(street_name.title().split())
        # Endpoints sorted so the key does not depend on which node the row
        # happened to store as `from`. Two rows describing the same span must
        # produce the same key or the graph gains a phantom node.
        first, second = sorted((lo, hi))
        filled.append((seg_id, f"{street}_btw_{first}_{second}"))

    print(f"  segments examined      : {len(rows)}")
    print(f"  already keyed          : {sum(1 for r in rows if r[3])}")
    print(f"  derivable, will fill   : {len(filled)}")
    print(f"  skipped, no street_name: {skipped_no_name}")
    print(f"  skipped, ambiguous end : {skipped_ambiguous}")

    if args.dry_run:
        for seg_id, key in filled[:5]:
            print(f"    would set {seg_id} -> {key}")
        print("\n  dry run: nothing written")
        return 0

    if not filled:
        print("\n  nothing to fill")
        return 0

    # `AND block_key IS NULL` in the WHERE, not just the read: another process
    # may have filled the row between the SELECT above and this UPDATE.
    cur.executemany(
        "UPDATE street_segments SET block_key = %s "
        "WHERE segment_id = %s AND block_key IS NULL",
        [(key, seg_id) for seg_id, key in filled],
    )
    conn.commit()
    print(f"\n  wrote {cur.rowcount if cur.rowcount >= 0 else len(filled)} rows")

    cur.execute("SELECT count(*), count(block_key) FROM street_segments")
    total, keyed = cur.fetchone()
    print(f"  block_key coverage now : {keyed}/{total} ({keyed / total * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
