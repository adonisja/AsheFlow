# Test users from sync_test_users.py
TEST_USERS = [
    {"id": "d16be5f0-c021-70de-6a50-cc22a3880062", "name": "Timmy Trainee", "role": "trainee", "discord_id": "trainee#1234"},
    {"id": "b17b2530-0001-7015-b225-8b6346628d27", "name": "Manny Manager", "role": "management", "discord_id": "manager#1234"},
    {"id": "b11b2560-b041-707a-9b49-23883a0d86f1", "name": "Terry Trainer", "role": "trainer", "discord_id": "trainer#1234"},
    {"id": "e14b05e0-4031-705e-56a2-59fbe66b8171", "name": "Danny Driver", "role": "driver", "discord_id": "driver#1234"},
    {"id": "a1db5550-9041-7079-2b61-a921e9d7807a", "name": "Dizzy Dispatch", "role": "dispatch", "discord_id": "dispatch#1234"},
    {"id": "514ba500-b0d1-7071-302c-8e1a5f5cb0f9", "name": "Wally Walker", "role": "walker", "discord_id": "walker#1234"},
]
"""
Seed script for AsheFlow Dispatch system.
Run from inside the backend container:
    docker exec -it asheflow_backend python seed.py
"""

import random
import uuid
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee_off_day import EmployeeOffDay
from app.models.employee_relationship import EmployeeRelationship

# ── Data definitions ──────────────────────────────────────────────────────────

DRIVER_NAMES = [
    "Marcus Johnson", "Darius Webb", "Terrence Hill", "Calvin Brooks",
    "Antoine Reeves", "Jaylen Foster", "DeShawn Morris", "Malik Turner",
    "Alicia Monroe"
]

TRAINER_NAMES = [
    "Brandon Hayes", "Kenji Watanabe", "Omar Khalil", "Devon Hughes",
    "Rasheed Grant", "Carlos Mendez", "Tyrone Baker", "Isaiah Fletcher",
    "Nathan Cross", "Elijah Stone", "Samuel Okafor", "Victor Reyes",
    "Patrick Donnelly", "Andre Williams", "Keisha Simmons", "Tanya Griffith"
]

WALKER_NAMES = [
    "Jordan Smith", "Tyler Banks", "Devon Hughes", "Casey Morgan",
    "Avery Jenkins", "Reese Coleman", "Quinn Patterson", "Sage Fletcher",
    "River Daniels", "Skyler Grant", "Alexis Wade", "Cameron Bell",
    "Peyton Shaw", "Morgan Ellis", "Bailey Stone", "Hayden King",
    "Taylor Woods", "Dakota Cross", "Finley Pierce", "Kendall Russell",
    "Rowan Sullivan", "Emery Bryant", "Addison Powell", "Harper Long",
    "Parker James", "Sawyer Evans", "Spencer Ward", "Blake Dixon",
    "Drew Perkins", "Jules Watts", "Ari Marsh", "Remy Hawkins",
    "Phoenix Hunt", "Sage Barker", "Lennon Drake", "Harlow Reid",
    "Indigo Burns", "Zephyr Cole", "Onyx Fields", "Cleo Saunders"
]

TRUCK_NAMES = ["Morgan", "Atlas", "Eagle", "Omega", "Falcon", "Gemini", "Jackal"]

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKEND_DAYS = {"Friday", "Saturday", "Sunday"}

# Role-specific fav limits: FAV_LIMITS[employee_role][target_role] = max count
FAV_LIMITS = {
    "driver":  {"driver": 0, "trainer": 1, "walker": 2},
    "trainer": {"driver": 1, "trainer": 1, "walker": 2},
    "walker":  {"driver": 1, "trainer": 1, "walker": 2},
    "trainee": {"driver": 0, "trainer": 0, "walker": 0},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_discord_id(name: str) -> str:
    tag = random.randint(1000, 9999)
    return f"{name.split()[0].lower()}#{tag}"


def random_off_days() -> list[str]:
    """Pick 1–5 off days, guaranteeing at least one weekend day."""
    count = random.randint(1, 5)
    # Always include at least one weekend day
    guaranteed = random.choice(list(WEEKEND_DAYS))
    remaining_pool = [d for d in DAYS_OF_WEEK if d != guaranteed]
    extras = random.sample(remaining_pool, min(count - 1, len(remaining_pool)))
    return list(set([guaranteed] + extras))


# ── Seed function ─────────────────────────────────────────────────────────────

def seed():
    db = SessionLocal()


    try:
        # ── Clear only relationships and assignments, not employees ───────
        print("Clearing relationships and assignments...")
        db.query(EmployeeRelationship).delete()
        db.query(EmployeeOffDay).delete()
        db.query(AssignmentMember).delete()
        db.query(TruckAssignment).delete()
        db.commit()


        # ── Create test users if not present ──────────────────────────────
        print("Ensuring test users exist...")
        employees = []
        for u in TEST_USERS:
            emp = db.query(Employee).filter_by(id=uuid.UUID(u["id"])).first()
            if not emp:
                emp = Employee(
                    id=uuid.UUID(u["id"]),
                    name=u["name"],
                    role=u["role"],
                    discord_id=u["discord_id"],
                    is_active=True
                )
                db.add(emp)
            employees.append(emp)

        # ── Create seed employees if not present ─────────────────────────
        print("Ensuring seed employees exist...")
        for name in DRIVER_NAMES:
            emp = db.query(Employee).filter_by(name=name, role="driver").first()
            if not emp:
                emp = Employee(
                    id=uuid.uuid4(),
                    name=name,
                    discord_id=make_discord_id(name),
                    role="driver",
                    is_active=True
                )
                db.add(emp)
            employees.append(emp)

        for name in TRAINER_NAMES:
            emp = db.query(Employee).filter_by(name=name, role="trainer").first()
            if not emp:
                emp = Employee(
                    id=uuid.uuid4(),
                    name=name,
                    discord_id=make_discord_id(name),
                    role="trainer",
                    is_active=True
                )
                db.add(emp)
            employees.append(emp)

        for name in WALKER_NAMES:
            emp = db.query(Employee).filter_by(name=name, role="walker").first()
            if not emp:
                emp = Employee(
                    id=uuid.uuid4(),
                    name=name,
                    discord_id=make_discord_id(name),
                    role="walker",
                    is_active=True
                )
                db.add(emp)
            employees.append(emp)

        db.commit()
        print(f"  Ensured {len(employees)} employees exist")

        # ── Create trucks ──────────────────────────────────────────────────
        print("Ensuring trucks exist...")
        truck_count = 0
        for name in TRUCK_NAMES:
            truck = db.query(Truck).filter_by(name=name).first()
            if not truck:
                db.add(Truck(id=uuid.uuid4(), name=name, is_active=True))
                truck_count += 1
        db.commit()
        print(f"  Ensured {len(TRUCK_NAMES)} trucks exist, added {truck_count} new trucks")

        # ── Create off days ────────────────────────────────────────────────
        print("Creating off days...")
        off_day_count = 0
        for emp in employees:
            for day in random_off_days():
                db.add(EmployeeOffDay(
                    id=uuid.uuid4(),
                    employee_id=emp.id,
                    day_of_week=day,
                    status="approved"
                ))
                off_day_count += 1
        db.commit()
        print(f"  Created {off_day_count} off day records")

        # ── Create relationships ───────────────────────────────────────────
        print("Creating relationships...")
        rel_count = 0

        for emp in employees:
            if emp.role not in FAV_LIMITS:
                continue  # Only drivers, trainers, walkers get relationships
            others = [e for e in employees if e.id != emp.id]
            fav_ids = set()

            # Favorites: role-aware limits per FAV_LIMITS
            for target_role, limit in FAV_LIMITS[emp.role].items():
                if limit == 0:
                    continue
                role_pool = [e for e in others if e.role == target_role]
                count = random.randint(0, limit)
                targets = random.sample(role_pool, min(count, len(role_pool)))
                for target in targets:
                    db.add(EmployeeRelationship(
                        id=uuid.uuid4(),
                        employee_id=emp.id,
                        target_employee_id=target.id,
                        relationship_type="fav"
                    ))
                    fav_ids.add(target.id)
                    rel_count += 1

            # Bans: 0–2 (exclude already-fav targets)
            ban_pool = [e for e in others if e.id not in fav_ids]
            ban_count = random.randint(0, 2)
            ban_targets = random.sample(ban_pool, min(ban_count, len(ban_pool)))
            for target in ban_targets:
                db.add(EmployeeRelationship(
                    id=uuid.uuid4(),
                    employee_id=emp.id,
                    target_employee_id=target.id,
                    relationship_type="ban"
                ))
                rel_count += 1

        db.commit()
        print(f"  Created {rel_count} relationship records")

        print("\nSeed complete.")
        print(f"  Employees : {len(employees)}")
        print(f"  Trucks    : {len(TRUCK_NAMES)}")
        print(f"  Off days  : {off_day_count}")
        print(f"  Relations : {rel_count}")

    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
