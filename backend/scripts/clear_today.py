import sys, os
sys.path.insert(0, os.path.abspath('.'))
from datetime import date
from app.database import SessionLocal
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember

db = SessionLocal()
try:
    target = date.today()
    assignments = db.query(TruckAssignment).filter(TruckAssignment.date == target).all()
    for a in assignments:
        db.query(AssignmentMember).filter(AssignmentMember.assignment_id == a.id).delete()
        db.delete(a)
    db.commit()
    print(f"Deleted {len(assignments)} assignments for {target}")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
finally:
    db.close()
