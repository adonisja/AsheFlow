#!/usr/bin/env python3
"""Re-apply Personal Information erasures after a backup restore (ADR-493 D3).

MANDATORY STEP IN THE RESTORE RUNBOOK (ADR-349). Backups are Object-Locked for
30 days, so a restored database can predate erasures made since the snapshot —
restoring it silently brings erased addresses and package ids back. The ledger
(`pi_erasure_ledger`) records an HMAC of every erased value; this script hashes
every value currently stored in a registered column and erases the matches.

    cd backend
    python ../scripts/replay_erasures.py                 # report only
    python ../scripts/replay_erasures.py --commit        # apply
    python ../scripts/replay_erasures.py --since-days 45 --commit

Needs the same PI_ERASURE_HMAC_KEY the erasures were made with; a different key
matches nothing, and the script says so rather than reporting a clean zero.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings          # noqa: E402
from app.database import SessionLocal         # noqa: E402
from app.services.pi_erasure import replay_ledger  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since-days", type=int, default=31,
                    help="replay ledger entries newer than this (default 31: the 30-day backup lock + 1)")
    ap.add_argument("--commit", action="store_true", help="apply; without it, report and roll back")
    args = ap.parse_args()

    if not settings.pi_erasure_hmac_key:
        print("PI_ERASURE_HMAC_KEY is not set — cannot match ledger entries. Nothing done.")
        return 2

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    db = SessionLocal()
    try:
        out = replay_ledger(db, settings.pi_erasure_hmac_key, since)
        if out["entries"] and not out["erased"]:
            print("WARNING: ledger entries exist but no stored value matched. Either the restore "
                  "predates none of them (fine), or the key differs from the one used to erase.")
        if args.commit:
            db.commit()
            print(f"Applied: {out}")
        else:
            db.rollback()
            print(f"Report only (use --commit to apply): {out}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
