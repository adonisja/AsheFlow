import sys
import os
import uuid

# Add parent directory to path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee_off_day import EmployeeOffDay
from app.models.employee_relationship import EmployeeRelationship

TEST_USERS = [
    {"id": "d16be5f0-c021-70de-6a50-cc22a3880062", "name": "Timmy Trainee", "role": "trainee", "discord_id": "trainee#1234"},
    {"id": "b17b2530-0001-7015-b225-8b6346628d27", "name": "Manny Manager", "role": "management", "discord_id": "manager#1234"},
    {"id": "b11b2560-b041-707a-9b49-23883a0d86f1", "name": "Terry Trainer", "role": "trainer", "discord_id": "trainer#1234"},
    {"id": "e14b05e0-4031-705e-56a2-59fbe66b8171", "name": "Danny Driver", "role": "driver", "discord_id": "driver#1234"},
    {"id": "a1db5550-9041-7079-2b61-a921e9d7807a", "name": "Dizzy Dispatch", "role": "dispatch", "discord_id": "dispatch#1234"},
    {"id": "514ba500-b0d1-7071-302c-8e1a5f5cb0f9", "name": "Wally Walker", "role": "walker", "discord_id": "walker#1234"},
]

def seed_test_users():
    db = SessionLocal()
    try:
        print("Clearing old seed data...")
        db.query(EmployeeRelationship).delete()
        db.query(EmployeeOffDay).delete()
        db.query(AssignmentMember).delete()
        db.query(TruckAssignment).delete()
        db.query(Truck).delete()
        db.query(Employee).delete()
        db.commit()

        print("Inserting Cognito-synced users...")
        for u in TEST_USERS:
            emp = Employee(
                id=uuid.UUID(u["id"]),
                name=u["name"],
                role=u["role"],
                discord_id=u["discord_id"],
                is_active=True
            )
            db.add(emp)
        
        # Add basic trucks back
        trucks = ["Morgan", "Atlas", "Eagle"]
        for t in trucks:
            db.add(Truck(id=uuid.uuid4(), name=t, is_active=True))

        db.commit()
        print("Complete! New Employees in DB match Cognito UUIDs exactly.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_test_users()
