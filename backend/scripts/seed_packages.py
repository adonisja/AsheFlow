"""Generate a synthetic Amazon manifest CSV with 1500 packages for sort testing.

Produces a CSV file that exactly matches Amazon's Delivery Station manifest format
(the same columns the FileManifestIngestor expects). Upload it through the normal
production flow:

    1. POST /sort/upload  (multipart file upload) — triggers Celery enrichment
    2. Poll GET /sort/manifest/{date}/status until "ready"
    3. POST /sort/{date}/run  (with tote manifest body) — DBSCAN + truck zones
    4. POST /walker-routes/commit-sort — anchor-point walker sort per truck

Usage:
    cd backend
    python scripts/seed_packages.py                          # writes to /tmp/manifest_seed.csv
    python scripts/seed_packages.py --out ./manifest_seed.csv
    python scripts/seed_packages.py --count 1500 --out ./manifest_seed.csv
"""
from __future__ import annotations

import argparse
import os
import sys

# Allow running directly from the scripts/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.seed_manifest import generate_manifest, DEFAULT_COUNT

DEFAULT_OUT = "/tmp/manifest_seed.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic Amazon manifest CSV")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Number of packages")
    parser.add_argument("--out",   default=DEFAULT_OUT,              help="Output CSV path")
    args = parser.parse_args()

    result = generate_manifest(args.count)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(result.csv_bytes)

    print(f"Wrote {result.package_count} packages across {result.tote_count} totes ({result.ov_count} OVs) → {args.out}")
    print(f"Upload via:  POST /sort/upload  (multipart, field='file', sort_date=YYYY-MM-DD)")


if __name__ == "__main__":
    main()
