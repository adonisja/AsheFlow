"""Seed the role guides onto companies that already exist (ADR-494 D4).

WHY THIS IS NOT OPTIONAL
------------------------
The same change that adds `/my-role` also DROPS the GATE channel from two
notification types:

    graduation              GATE -> PROMPT
    operating_mode_change   GATE -> PROMPT

A PROMPT's justification is that its action link carries the information the
GATE used to force people to sit in front of. Both links point at `/my-role`.

New companies get their rows from `seed_role_guides` at creation. An EXISTING
company has no `role_guides` rows, so on deploy its graduating walkers get a
prompt whose only control 404s — which is strictly worse than the modal it
replaced. The gate at least said something.

So this runs as part of the deploy, not afterwards.

IDEMPOTENT, AND IT RESPECTS EDITS
---------------------------------
`seed_role_guides` checks `seed_key` per company before inserting, and the
unique index on (company_id, role, operating_mode) is the backstop. It also
skips any row with `edited_at IS NOT NULL`, so re-running after a tenant has
rewritten a guide does not revert them. Safe to re-run after a partial failure.

BOTH MODES, ALWAYS
------------------
Every company gets all 20 rows — 10 roles x 2 modes — not just the 10 for its
current mode. A tenant who switches mode finds the other set already written,
which is the point: `operating_mode_change` fires AT the switch, and its link
must resolve the moment it arrives rather than after a backfill nobody
scheduled.

USAGE
-----
    python3 scripts/backfill_role_guides.py            # report only
    python3 scripts/backfill_role_guides.py --commit   # write
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal                        # noqa: E402
from app.models.company import Company, CompanyConfig        # noqa: E402
from app.models.role_guide import RoleGuide                   # noqa: E402
from app.services.role_guide_seeds import (                   # noqa: E402
    MODES, SEED_VERSION, SEEDED_ROLES, iter_seeds,
)
from app.services.seed_role_guides import seed_role_guides    # noqa: E402

EXPECTED_PER_COMPANY = len(SEEDED_ROLES) * len(MODES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="write the rows (default is a dry run)")
    args = ap.parse_args()

    # Fails loudly here rather than per-company if a role has no guide text.
    all_keys = {key for *_, key in iter_seeds()}
    assert len(all_keys) == EXPECTED_PER_COMPANY, (
        f"{len(all_keys)} seed keys for {len(SEEDED_ROLES)} roles x "
        f"{len(MODES)} modes — expected {EXPECTED_PER_COMPANY}"
    )

    db = SessionLocal()
    try:
        companies = db.query(Company.id, Company.name).all()
        modes = {
            c.company_id: c.operating_mode
            for c in db.query(CompanyConfig.company_id, CompanyConfig.operating_mode).all()
        }

        have: dict[object, set[str]] = {}
        edited: dict[object, int] = {}
        for cid, key, ed in db.query(
            RoleGuide.company_id, RoleGuide.seed_key, RoleGuide.edited_at,
        ).filter(RoleGuide.seed_key.isnot(None)).all():
            have.setdefault(cid, set()).add(key)
            if ed is not None:
                edited[cid] = edited.get(cid, 0) + 1

        print(f"{len(companies)} company(ies), seed version {SEED_VERSION}, "
              f"{EXPECTED_PER_COMPANY} guides each\n")

        totals = {"inserted": 0, "updated": 0, "skipped_edited": 0, "skipped_current": 0}
        would_create = 0

        for cid, name in companies:
            mine = have.get(cid, set())
            missing = len(all_keys - mine)
            would_create += missing
            mode = modes.get(cid, "workforce (no config)")
            note = f"+{missing}" if missing else "ok"
            extra = f"  [{edited[cid]} tenant-edited, untouched]" if cid in edited else ""
            print(f"  {str(cid)[:8]}  {str(name)[:28]:28}  mode={mode:10}  {note}{extra}")

            if args.commit:
                counts = seed_role_guides(db, cid)
                for k, v in counts.items():
                    totals[k] += v

        if args.commit:
            db.commit()
            print(f"\ncommitted: {totals}")
            if totals["skipped_edited"]:
                print(f"{totals['skipped_edited']} tenant-edited guide(s) left alone, "
                      f"which is ADR-494 D4 working — a rewrite is theirs permanently.")
        else:
            print(f"\nDRY RUN — would create {would_create} guide(s)")
            print("re-run with --commit to write")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
