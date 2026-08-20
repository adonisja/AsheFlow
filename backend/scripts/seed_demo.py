"""Seed two demo companies with mirrored operational data for isolation testing.

Idempotent — safe to run multiple times. Uses fixed UUIDs so the same IDs
are stable across dev and staging, making cross-environment debugging easier.

Company A — DSP Test Company  (a0000000-0000-0000-0000-000000000001)
Company B — Rival DSP Corp    (b0000000-0000-0000-0000-000000000002)

Both companies get the same roster shape and truck names so you can verify
that authenticated users from company A never see company B's records
and vice versa (multi-tenant isolation testing).

Usage:
    docker compose exec backend python scripts/seed_demo.py
    docker compose exec backend python scripts/seed_demo.py --wipe-company-b
"""

import sys
import os
import uuid
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.company import Company, CompanyConfig
from app.models.employee import Employee
from app.models.truck import Truck

# ── Fixed company IDs ──────────────────────────────────────────────────────────
COMPANY_A_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")
COMPANY_B_ID = uuid.UUID("b0000000-0000-0000-0000-000000000002")

COMPANIES = [
    {
        "id":       COMPANY_A_ID,
        "name":     "DSP Test Company",
        "slug":     "dsp-test",
        "timezone": "America/New_York",
    },
    {
        "id":       COMPANY_B_ID,
        "name":     "Rival DSP Corp",
        "slug":     "rival-dsp",
        "timezone": "America/New_York",
    },
]

# ── Truck names — unique per company (global unique constraint on trucks.name) ─
# Company A uses the real names already in dev/staging.
# Company B gets a "B-" prefix so names don't collide.
TRUCK_NAMES_A = ["Atlas", "Eagle", "Falcon", "Gemini", "Jackal", "Morgan", "Omega"]
TRUCK_NAMES_B = ["B-Atlas", "B-Eagle", "B-Falcon", "B-Gemini", "B-Jackal", "B-Morgan", "B-Omega"]

# ── Roster template — same roles for both companies ───────────────────────────
# username will be suffixed with -a / -b to keep them globally unique.
# cognito_sub is None for all seeded employees — they have no real Cognito account.
# dispatch.test and driver.test already have real Cognito accounts on company A;
# those are preserved by the ON CONFLICT DO NOTHING pattern (we skip them here).
ROSTER_TEMPLATE = [
    {"name": "Admin User",       "role": "admin"},
    {"name": "Manager User",     "role": "management"},
    {"name": "Dispatch User",    "role": "dispatch"},
    {"name": "Driver One",       "role": "driver"},
    {"name": "Driver Two",       "role": "driver"},
    {"name": "Driver Three",     "role": "driver"},
    {"name": "Walker One",       "role": "walker"},
    {"name": "Walker Two",       "role": "walker"},
    {"name": "Trainer One",      "role": "trainer"},
    {"name": "Trainee One",      "role": "trainee"},
    {"name": "Trainee Two",      "role": "trainee"},
]

# Deterministic UUID: namespace + company_suffix + name so re-runs produce same IDs
_NS = uuid.UUID("00000000-dead-beef-cafe-000000000000")


def _det_uuid(company_id: uuid.UUID, label: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{company_id}:{label}")


def seed_company(db, company_def: dict, suffix: str, truck_names: list) -> None:
    cid = company_def["id"]

    # Company row
    if not db.query(Company).filter(Company.id == cid).first():
        db.add(Company(
            id=cid,
            name=company_def["name"],
            slug=company_def["slug"],
            timezone=company_def["timezone"],
            is_active=True,
            # ADR-280: this script CREATES the disposable tenants, so it is the
            # one place that may classify them. Without this they inherit the
            # 'live' default and every other seed script correctly refuses them.
            data_class="seed",
        ))
        print(f"  + company  {company_def['name']}")
    else:
        print(f"  = company  {company_def['name']} (exists)")

    # CompanyConfig
    if not db.query(CompanyConfig).filter(CompanyConfig.company_id == cid).first():
        db.add(CompanyConfig(
            id=_det_uuid(cid, "config"),
            company_id=cid,
            is_configured=True,
        ))
        print(f"  + config")
    else:
        print(f"  = config (exists)")

    # Trucks — look up by (company_id, name) since name has a global unique index
    # and existing trucks in dev may have different UUIDs from our deterministic ones.
    for truck_name in truck_names:
        existing = db.query(Truck).filter(
            Truck.company_id == cid, Truck.name == truck_name
        ).first()
        if not existing:
            db.add(Truck(
                id=_det_uuid(cid, f"truck:{truck_name}"),
                name=truck_name,
                is_active=True,
                company_id=cid,
            ))
            print(f"  + truck    {truck_name}")
        else:
            print(f"  = truck    {truck_name} (exists)")

    # Employees
    for emp_def in ROSTER_TEMPLATE:
        username = emp_def["name"].lower().replace(" ", ".") + f"-{suffix}"
        eid = _det_uuid(cid, f"employee:{username}")
        if not db.query(Employee).filter(Employee.id == eid).first():
            db.add(Employee(
                id=eid,
                company_id=cid,
                name=emp_def["name"],
                role=emp_def["role"],
                username=username,
                email=f"{username}@demo.asheflow.internal",
                is_active=True,
                account_status="active",
                hr_system_id_adp=_det_uuid(cid, f"adp:{username}"),
                hr_system_id_adp_verified=False,
            ))
            print(f"  + employee {emp_def['name']} ({emp_def['role']}) [{suffix}]")
        else:
            print(f"  = employee {username} (exists)")

    db.commit()


def wipe_company_b(db) -> None:
    """Remove all company B data — useful to reset isolation test state."""
    cid = COMPANY_B_ID
    deleted = db.query(Employee).filter(Employee.company_id == cid).delete()
    print(f"  - deleted {deleted} employees from company B")
    deleted = db.query(Truck).filter(Truck.company_id == cid).delete()
    print(f"  - deleted {deleted} trucks from company B")
    db.query(CompanyConfig).filter(CompanyConfig.company_id == cid).delete()
    db.query(Company).filter(Company.id == cid).delete()
    db.commit()
    print("  company B wiped.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe-company-b", action="store_true",
                        help="Delete all company B data before re-seeding")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.wipe_company_b:
            print("Wiping company B...")
            wipe_company_b(db)

        print("\nSeeding Company A (DSP Test Company)...")
        seed_company(db, COMPANIES[0], suffix="a", truck_names=TRUCK_NAMES_A)

        print("\nSeeding Company B (Rival DSP Corp)...")
        seed_company(db, COMPANIES[1], suffix="b", truck_names=TRUCK_NAMES_B)

        print("\nDone.")
        print("\nIsolation test accounts:")
        print("  Company A dispatch: dispatch.test (real Cognito account)")
        print("  Company A driver:   driver.test   (real Cognito account)")
        print("  Company B admin:    admin.user-b  (no Cognito — use super_admin to verify isolation)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
