import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import date
from app.database import SessionLocal
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember

db = SessionLocal()
try:
    today = date.today()
    print(f"Deleting assignments for {today}...")
    
    # Find all truck assignments for today
    assignments = db.query(TruckAssignment).filter(TruckAssignment.date == today).all()
    
    deleted_members = 0
    deleted_assignments = 0
    
    for a in assignments:
        # Delete members first due to foreign keys, or just let cascade do it if configured
        members = db.query(AssignmentMember).filter(AssignmentMember.assignment_id == a.id).delete()
        deleted_members += members
        
        db.delete(a)
        deleted_assignments += 1
        
    db.commit()
    print(f"Successfully deleted {deleted_assignments} truck assignments and {deleted_members} crew assignments for {today}.")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
finally:
    db.close()
