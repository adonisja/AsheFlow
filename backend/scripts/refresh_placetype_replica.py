"""Copy PlaceType from the master into this environment's replica (ADR-409 D6/D8).

WHY A COPY AND NOT A SHARED CONNECTION
--------------------------------------
An earlier draft had staging and local connect directly to the master. The
reference-data literature calls PlaceType's shape a "Reference Data Holder" —
the golden copy, read-only, one version of the truth — and agrees it should be
centrally managed. It also says staging should not hold a connection to
production, and one objection survives scrutiny: nothing would ENFORCE that the
connection stays read-only. A misconfiguration reaches production.

So: production writes the master, and every other environment reads a copy of
what production wrote. Read-only becomes a property of the topology rather than
a permission somebody has to remember to set.

WHY NOT STREAMING REPLICATION
-----------------------------
Two tables of slow-moving reference data do not need WAL shipping, and setting
it up would couple the databases at the storage layer — reintroducing the
dependency the copy exists to remove. A scheduled job is enough because street
topology changes on the order of years (ADR-409 D7).

THREE PROPERTIES THAT MATTER (D8)
---------------------------------
- **Idempotent.** Re-running changes nothing; a half-finished run resumes. Same
  discipline as the ADR-408 backfill.
- **Additive.** A row missing from the master is NEVER deleted from the replica.
  Reference data is append-mostly, and a deletion propagating from a bad master
  run would empty a working environment while looking like a successful sync.
- **Reports rather than asserts.** Row counts differ between environments until
  the first run completes, so a job that failed on a count mismatch would fail
  every time until it happened to succeed once.

USAGE
-----
    PLACETYPE_MASTER_URL=postgresql://...  # read from
    DATABASE_URL=postgresql://...          # write to (this environment)
    python scripts/refresh_placetype_replica.py [--dry-run] [--table segments]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from typing import Iterable

# The two tables the ADR-237 boundary owns, and their natural keys. Nothing else
# is copied: `building_profiles` and `company_zones` are tenant data and stay
# where they are (ADR-409 D1).
_TABLES = {
    "segments": ("street_segments", "segment_id"),
    "buildings": ("building_profile_library", "normalised_address"),
}

# `id` is never COPIED from the master, but it must still be SUPPLIED: the
# column is NOT NULL with no database-level default (SQLAlchemy generates the
# uuid4 in Python, and this database has no pgcrypto). So the replica mints its
# own.
#
# Deliberately not copied. The surrogate key is local: the same street carrying
# different ids in different environments is correct, because nothing joins on
# it across the boundary — `segment_id` and `normalised_address` are what
# identify a row, and those ARE copied.
_SKIP_COLUMNS = {"id"}

_BATCH = 500


def _columns(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [c for (c,) in cur.fetchall() if c not in _SKIP_COLUMNS]


def _refresh_one(src_cur, dst_cur, table: str, key: str, dry_run: bool) -> dict:
    src_cols = _columns(src_cur, table)
    dst_cols = _columns(dst_cur, table)

    # Intersect, do not assume. The replica may run an older migration than the
    # master during a deploy window; copying a column the replica lacks fails the
    # whole run, and copying only what both have degrades to a partial refresh
    # that completes. A column present in one and not the other is REPORTED.
    cols = [c for c in src_cols if c in dst_cols]
    missing_here = sorted(set(src_cols) - set(dst_cols))
    extra_here = sorted(set(dst_cols) - set(src_cols))

    src_cur.execute(f"SELECT {', '.join(cols)} FROM {table}")
    rows = src_cur.fetchall()

    dst_cur.execute(f"SELECT count(*) FROM {table}")
    before = dst_cur.fetchone()[0]

    stats = {
        "table": table, "master_rows": len(rows), "replica_before": before,
        "columns_copied": len(cols),
        "columns_missing_in_replica": missing_here,
        "columns_extra_in_replica": extra_here,
    }
    if dry_run or not rows:
        stats["replica_after"] = before
        return stats

    # Mint a local id per row (see _SKIP_COLUMNS). On a conflict the existing
    # row keeps ITS id — `id` is absent from the SET clause below — so a refresh
    # never renumbers rows the replica already had.
    insert_cols = ["id"] + cols
    rows = [(str(uuid.uuid4()),) + tuple(r) for r in rows]

    placeholders = ", ".join(["%s"] * len(insert_cols))
    # ON CONFLICT DO UPDATE, not DELETE-then-INSERT: additive (D8). A row the
    # master no longer has stays in the replica rather than vanishing.
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
    sql = (
        f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
    )

    for i in range(0, len(rows), _BATCH):
        dst_cur.executemany(sql, rows[i:i + _BATCH])

    dst_cur.execute(f"SELECT count(*) FROM {table}")
    stats["replica_after"] = dst_cur.fetchone()[0]
    return stats


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--table", choices=sorted(_TABLES), action="append",
                    help="refresh only this table (repeatable); default is both")
    args = ap.parse_args(list(argv) if argv is not None else None)

    master = os.environ.get("PLACETYPE_MASTER_URL")
    replica = os.environ.get("DATABASE_URL")
    if not master:
        print("PLACETYPE_MASTER_URL is not set — nothing to copy from",
              file=sys.stderr)
        return 2
    if not replica:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if master == replica:
        # This is production, which WRITES the master. Refreshing it from itself
        # is a no-op at best and a confusing log line at worst.
        print("  master and replica are the same database; nothing to do")
        return 0

    import psycopg2
    src = psycopg2.connect(master, connect_timeout=10)
    dst = psycopg2.connect(replica, connect_timeout=10)
    src_cur, dst_cur = src.cursor(), dst.cursor()

    wanted = args.table or sorted(_TABLES)
    results = []
    try:
        for name in wanted:
            table, key = _TABLES[name]
            results.append(_refresh_one(src_cur, dst_cur, table, key, args.dry_run))
        if not args.dry_run:
            # One transaction for both tables: a replica holding half a refresh
            # is a graph with segments the buildings do not match.
            dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    for r in results:
        print(f"  {r['table']}")
        print(f"    master rows      : {r['master_rows']}")
        print(f"    replica before   : {r['replica_before']}")
        print(f"    replica after    : {r['replica_after']}")
        print(f"    columns copied   : {r['columns_copied']}")
        if r["columns_missing_in_replica"]:
            # Reported, not fatal (D8): a deploy window where the replica runs an
            # older migration is normal and self-corrects.
            print(f"    NOT copied (replica lacks): {r['columns_missing_in_replica']}")
        if r["columns_extra_in_replica"]:
            print(f"    replica-only columns      : {r['columns_extra_in_replica']}")
    if args.dry_run:
        print("\n  dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
