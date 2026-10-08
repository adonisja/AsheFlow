"""Seed 8 simulation trainee employees.

reset_on_graduation was removed in ADR-487 D11c: it existed for one named
simulation account, and graduation is now unconditional — a simulation trainee
graduates to walker like anybody else.

Idempotent — skips any discord_id that already exists.
Run from inside the container:
    docker compose exec backend python scripts/seed_trainees.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.employee import Employee


NEW_TRAINEES = [
    {"name": "Alex Rivera",    "discord_id": "seed_trainee_001"},
    {"name": "Jordan Wu",      "discord_id": "seed_trainee_002"},
    {"name": "Morgan Davis",   "discord_id": "seed_trainee_003"},
    {"name": "Casey Thompson", "discord_id": "seed_trainee_004"},
    {"name": "Riley Patel",    "discord_id": "seed_trainee_005"},
    {"name": "Taylor Brooks",  "discord_id": "seed_trainee_006"},
    {"name": "Drew Okafor",    "discord_id": "seed_trainee_007"},
    {"name": "Cameron Singh",  "discord_id": "seed_trainee_008"},
]


def main():
    db = SessionLocal()
    try:
        # Seed new trainees
        added = 0
        skipped = 0
        for data in NEW_TRAINEES:
            existing = db.query(Employee).filter(
                Employee.discord_id == data["discord_id"]
            ).first()
            if existing:
                print(f"  SKIP {data['name']} (discord_id already exists)")
                skipped += 1
                continue

            emp = Employee(
                name=data["name"],
                discord_id=data["discord_id"],
                role="trainee",
                is_active=True,
                account_status="active",
            )
            db.add(emp)
            print(f"  ADD  {data['name']}")
            added += 1

        db.commit()
        print(f"\nDone. Added {added} trainees, skipped {skipped}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
