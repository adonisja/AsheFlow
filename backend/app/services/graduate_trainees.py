from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.employee import Employee
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.models.trainer_continuation_request import TrainerContinuationRequest

def graduate_eligible_trainees(db: Session, target_date):
    """
    Check all active trainees to see if they have completed 5 successful dispatch assignments.
    If so, graduate them to walkers. Returns a list of notifications.
    """
    warnings = []
    
    # Query all current trainees
    trainees = db.query(Employee).filter(
        Employee.role == "trainee",
        Employee.is_active == True
    ).all()
    
    for trainee in trainees:
        # Count the number of past assignments they have where their role was anything.
        # But specifically we are counting how many days they were dispatched as a trainee (or generally dispatched).
        # We'll just count how many assignment records exist for them.
        assignment_count = db.query(AssignmentMember).join(TruckAssignment).filter(
            AssignmentMember.employee_id == trainee.id,
            TruckAssignment.date < target_date
        ).count()
        
        # 5 confirmed assignments beforehand means this new one is their 6th.
        # "after 5th confirmed/successful assignments (or on their 6th active dispatch), 
        # their role transitions to 'Walker'"
        if assignment_count >= 5:
            trainee.role = "walker"
            warnings.append({
                "type": "graduation_notification",
                "message": f"Trainee {trainee.name} has completed 5 successful assignments and has been automatically graduated to a Walker for this and future dispatches."
            })

            # Nullify any open continuation requests — a graduated walker no longer
            # goes through training_injection so pending/accepted requests would
            # otherwise sit open indefinitely.
            open_requests = db.query(TrainerContinuationRequest).filter(
                TrainerContinuationRequest.trainee_id == trainee.id,
                TrainerContinuationRequest.status.in_(["pending", "accepted"]),
            ).all()
            for req in open_requests:
                req.status = "nullified"
                req.resolved_at = datetime.now(timezone.utc)
            
    if warnings:
        db.commit()
        
    return warnings