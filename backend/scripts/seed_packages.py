"""Generate a synthetic Amazon manifest CSV for sort testing.

Produces a CSV that exactly matches Amazon's Delivery Station manifest format
(the same columns FileManifestIngestor expects). Upload through the normal flow:

    1. POST /sort/upload  (multipart file upload) — triggers Celery enrichment
    2. Poll GET /sort/manifest/{date}/status until "ready"
    3. POST /sort/{date}/run  (with tote manifest body) — DBSCAN + truck zones
    4. POST /walker-routes/commit-sort — anchor-point walker sort per truck

The generated manifest includes three categories of packages to exercise the
full verification pipeline:

  IN-ZONE      (~96.5%)  Normal Manhattan packages spread across all blocks.
  OUT-OF-ZONE  (~1.5%)   Addresses in Queens/Brooklyn — DBSCAN outliers with
                          no cluster assignment; unresolvable by tier1_verify.
  MISROUTED    (~2.5%)   In-zone packages deliberately placed in a tote from
                          a distant zone — tier1_verify should flag as misaligned.

Usage:
    cd backend
    python scripts/seed_packages.py
    python scripts/seed_packages.py --count 10000 --out ./manifest_seed.csv
    python scripts/seed_packages.py --count 10000 --seed 99  # reproducible run
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.seed_manifest import generate_manifest, DEFAULT_COUNT

DEFAULT_OUT = "/tmp/manifest_seed.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic Amazon manifest CSV")
    parser.add_argument("--count", type=int,   default=DEFAULT_COUNT, help=f"Total packages (default {DEFAULT_COUNT})")
    parser.add_argument("--out",               default=DEFAULT_OUT,   help="Output CSV path")
    parser.add_argument("--seed", type=int,    default=None,          help="RNG seed for reproducible output (default: random)")
    parser.add_argument("--ooz-pct",  type=float, default=0.015,      help="Fraction of out-of-zone packages (default 0.015)")
    parser.add_argument("--miss-pct", type=float, default=0.025,      help="Fraction of misrouted packages (default 0.025)")
    args = parser.parse_args()

    result = generate_manifest(
        count            = args.count,
        seed             = args.seed,
        out_of_zone_pct  = args.ooz_pct,
        misrouted_pct    = args.miss_pct,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(result.csv_bytes)

    print(f"Wrote {result.package_count} packages → {args.out}")
    print(f"  Totes:       {result.tote_count}")
    print(f"  OV packages: {result.ov_count}")
    print(f"  Out-of-zone: {result.out_of_zone_count}  (DBSCAN outliers — unresolvable)")
    print(f"  Misrouted:   {result.misrouted_count}  (wrong tote — tier1_verify should flag)")
    print()
    print(f"Upload via:  POST /sort/upload  (multipart, field='file', sort_date=YYYY-MM-DD)")


if __name__ == "__main__":
    main()
