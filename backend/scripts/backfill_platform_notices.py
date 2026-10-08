"""Seed the platform notices onto companies that already exist (ADR-488).

WHY THIS IS NOT OPTIONAL
------------------------
The same change that adds the notice system DELETES four beat entries:

    warn-before-mfa-deadline
    dispatch-finalization-reminder
    fuel-log-reminder-first
    fuel-log-reminder-second

New companies get their notices from `seed_platform_notices` at creation. An
EXISTING company has no `notice_templates` rows, so on deploy it loses four
reminders and gains nothing — silently, because a sweep over zero rows is a
successful sweep.

So this must run as part of the deploy, not afterwards when somebody notices
drivers have stopped being reminded about fuel logs.

IDEMPOTENT
----------
`seed_platform_notices` checks `seed_key` per company before inserting, and the
partial unique index on (company_id, seed_key) is the backstop. Running this
twice creates nothing the second time, so it is safe to re-run after a partial
failure.

WHAT IT DOES NOT DO
-------------------
It does not configure anchors. A company with no `shift_end` gets a
`fuel_log_missing` notice that cannot fire, and the sweep will report it as
unservable and raise a platform alert naming the column (ADR-488 D3). That is
the intended behaviour: the alternative is guessing an hour, which is the
"comment as a default" pattern ADR-482 removed.

Expect that alert for under-configured tenants on the first tick. It is a
configuration gap this makes VISIBLE, not one it creates.

USAGE
-----
    python3 scripts/backfill_platform_notices.py            # report only
    python3 scripts/backfill_platform_notices.py --commit   # write
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal                      # noqa: E402
from app.models.company import Company, CompanyConfig      # noqa: E402
from app.models.notice import NoticeTemplate               # noqa: E402
from app.services.notice_seeds import (                    # noqa: E402
    PLATFORM_NOTICES, seed_platform_notices,
)
from app.models.notice import CONFIG_BACKED_ANCHORS, Anchor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="write the rows (default is a dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        companies = db.query(Company.id, Company.name).all()
        cfgs = {c.company_id: c for c in db.query(CompanyConfig).all()}
        existing = {}
        for cid, key in db.query(
            NoticeTemplate.company_id, NoticeTemplate.seed_key,
        ).filter(NoticeTemplate.seed_key.isnot(None)).all():
            existing.setdefault(cid, set()).add(key)

        total_created = 0
        unservable: list[str] = []

        print(f"{len(companies)} company(ies)\n")
        for cid, name in companies:
            have = existing.get(cid, set())
            missing = [s.seed_key for s in PLATFORM_NOTICES if s.seed_key not in have]

            # Report which of the seeded notices this tenant cannot actually
            # serve, so the deploy knows what to expect on the first tick.
            cfg = cfgs.get(cid)
            blocked = []
            for seed in PLATFORM_NOTICES:
                if Anchor(seed.anchor) not in CONFIG_BACKED_ANCHORS:
                    continue
                if cfg is None or getattr(cfg, str(seed.anchor), None) is None:
                    blocked.append(f"{seed.seed_key}({seed.anchor})")

            status = f"+{len(missing)}" if missing else "ok"
            print(f"  {str(cid)[:8]}  {str(name)[:28]:28}  {status}")
            if blocked:
                print(f"            unservable until configured: {', '.join(blocked)}")
                unservable.extend(blocked)

            if args.commit and missing:
                total_created += seed_platform_notices(db, cid)

        if args.commit:
            db.commit()
            print(f"\ncommitted: {total_created} notice(s) created")
        else:
            print(f"\nDRY RUN — would create {sum(1 for cid, _ in companies for s in PLATFORM_NOTICES if s.seed_key not in existing.get(cid, set()))} notice(s)")
            print("re-run with --commit to write")

        if unservable:
            print(f"\n{len(unservable)} notice(s) will report as unservable until "
                  f"their anchor column is set. This is ADR-488 D3 working, not "
                  f"a failure — the sweep names the column on the alerts board.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
