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
        # ── Clear existing data (children before parents) ──────────────────
        print("Clearing existing seed data...")
        db.query(EmployeeRelationship).delete()
        db.query(EmployeeOffDay).delete()
        db.query(AssignmentMember).delete()
        db.query(TruckAssignment).delete()
        db.query(Truck).delete()
        db.query(Employee).delete()
        db.commit()

        # ── Create employees ───────────────────────────────────────────────
        print("Creating employees...")
        employees = []

        for name in DRIVER_NAMES:
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
        print(f"  Created {len(employees)} employees")

        # ── Create trucks ──────────────────────────────────────────────────
        print("Creating trucks...")
        for name in TRUCK_NAMES:
            db.add(Truck(id=uuid.uuid4(), name=name, is_active=True))
        db.commit()
        print(f"  Created {len(TRUCK_NAMES)} trucks")

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
