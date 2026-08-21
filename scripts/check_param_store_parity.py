#!/usr/bin/env python3
"""Compare /asheflow/staging/ and /asheflow/prod/ in SSM Parameter Store.

WHY THIS EXISTS (ADR-283)
-------------------------
`backend/.env` is regenerated from Parameter Store on every deploy, so the store
IS the configuration. A key present in one environment and absent in the other
is a deploy-time failure or a silently-disabled feature, and nothing surfaces it
until someone deploys.

Found on the first run: prod was missing GEOCLIENT_APP_KEY (which CI hard-fails
on) plus the two ORE keys (which fail silently — see ADR-283).

Usage:
    python3 scripts/check_param_store_parity.py

Exits non-zero when the two environments differ, so it can gate a deploy.
Values are never read — only names. Use --with-values never; there is no such
flag by design.
"""
import sys

import boto3

REGION = "us-east-2"
PATHS = {"staging": "/asheflow/staging/", "prod": "/asheflow/prod/"}

# Keys that legitimately differ between environments, with the reason.
EXPECTED_DIFFERENCES = {
    # Supplied to the backend by docker-compose from POSTGRES_*; staging carries
    # an explicit override for an external DB host.
    "DATABASE_URL",
    # Bot container credentials; staging runs a live Discord bot, prod does not.
    "BOT_USERNAME",
    "BOT_PASSWORD",
}


def names_for(client, path: str) -> set[str]:
    pag = client.get_paginator("get_parameters_by_path")
    out = set()
    for page in pag.paginate(Path=path, WithDecryption=False):
        out |= {p["Name"].rsplit("/", 1)[-1] for p in page["Parameters"]}
    return out


def main() -> int:
    client = boto3.client("ssm", region_name=REGION)
    found = {env: names_for(client, path) for env, path in PATHS.items()}

    for env, keys in found.items():
        print(f"{env:<8} {len(keys)} parameters")

    problems = []
    for env, other in (("staging", "prod"), ("prod", "staging")):
        missing = found[other] - found[env] - EXPECTED_DIFFERENCES
        for key in sorted(missing):
            problems.append(f"{key} is in {other} but NOT in {env}")

    print()
    if not problems:
        print("PARITY OK — no unexpected differences")
        return 0

    print("PARITY DRIFT:")
    for p in problems:
        print(f"  {p}")
    print(
        "\nAdd the missing parameter, or add it to EXPECTED_DIFFERENCES with a "
        "reason if the difference is intentional."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
