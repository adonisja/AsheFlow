import uuid
import random
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from datetime import date, timedelta
import sys

def seed_fake_dispatch():
    db = SessionLocal()
    today = date.today()
    try:
        trucks = db.query(Truck).all()
        drivers = db.query(Employee).filter(Employee.role == 'driver').all()
        trainers = db.query(Employee).filter(Employee.role == 'trainer').all()
        walkers = db.query(Employee).filter(Employee.role == 'walker').all()

        if not trucks or not drivers:
            print("No trucks or drivers!")
            return

        print("Deleting old assignments")
        db.query(AssignmentMember).delete()
        db.query(TruckAssignment).delete()
        db.commit()

        # Generate dispatch for today and previous 14 days
        for i in range(14, -1, -1):
            target_date = today - timedelta(days=i)
            # Skip some random days so it's not perfectly continuous
            if target_date.weekday() == 6: # skip sundays just to make it realistic
                continue
                
            print(f"Creating fake assignments for {target_date}")
            
            # Use random trucks
            day_trucks = random.sample(trucks, min(5, len(trucks)))
            random.shuffle(drivers)
            random.shuffle(trainers)
            random.shuffle(walkers)
            
            d_idx = 0
            t_idx = 0
            w_idx = 0
            
            for index, truck in enumerate(day_trucks):
                if d_idx >= len(drivers):
                    break
                    
                ta = TruckAssignment(
                    id=uuid.uuid4(),
                    truck_id=truck.id,
                    date=target_date,
                    status="completed"
                )
                db.add(ta)
                db.commit() # commit to get id
                
                # Add driver
                driver = drivers[d_idx]
                d_idx += 1
                db.add(AssignmentMember(
                    id=uuid.uuid4(),
                    assignment_id=ta.id,
                    employee_id=driver.id,
                    role="driver"
                ))
                
                # Add a trainer
                if t_idx < len(trainers):
                    trainer = trainers[t_idx]
                    t_idx += 1
                    db.add(AssignmentMember(
                        id=uuid.uuid4(),
                        assignment_id=ta.id,
                        employee_id=trainer.id,
                        role="trainer"
                    ))
                    
                # Add a walker
                if w_idx < len(walkers):
                    walker = walkers[w_idx]
                    w_idx += 1
                    db.add(AssignmentMember(
                        id=uuid.uuid4(),
                        assignment_id=ta.id,
                        employee_id=walker.id,
                        role="walker"
                    ))
            
            db.commit()
            print("Success")
    finally:
        db.close()

if __name__ == "__main__":
    seed_fake_dispatch()
