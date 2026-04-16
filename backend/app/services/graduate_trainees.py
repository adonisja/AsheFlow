from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.notification import Notification


def graduate_eligible_trainees(db: Session, target_date):
    """Check all active trainees for 5+ completed dispatch assignments.

    Graduates eligible trainees to walker, nullifies their open continuation
    requests, and fires a Notification to every active management/admin/dispatch
    employee so the event is visible in the app.

    Returns a list of warning dicts for the dispatch run summary.
    """
    warnings = []

    trainees = db.query(Employee).filter(
        Employee.role == "trainee",
        Employee.is_active == True,
    ).all()

    # Fetch notification recipients once — all active privileged staff.
    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin", "dispatch"]),
        Employee.is_active == True,
    ).all()

    for trainee in trainees:
        assignment_count = (
            db.query(AssignmentMember)
            .join(TruckAssignment)
            .filter(
                AssignmentMember.employee_id == trainee.id,
                TruckAssignment.date < target_date,
            )
            .count()
        )

        if assignment_count >= 5:
            trainee.role = "walker"

            message = (
                f"{trainee.name} has completed {assignment_count} dispatch assignments "
                f"and was automatically graduated from Trainee to Walker on {target_date}."
            )

            # Notify every management/admin/dispatch employee.
            for recipient in recipients:
                db.add(Notification(
                    employee_id=recipient.id,
                    type="trainee_graduated",
                    message=message,
                ))

            # Also notify the trainee themselves.
            db.add(Notification(
                employee_id=trainee.id,
                type="trainee_graduated",
                message=(
                    f"Congratulations! You have completed {assignment_count} dispatch assignments "
                    f"and have been promoted to Walker effective {target_date}."
                ),
            ))

            # Nullify open continuation requests — graduated walkers no longer go
            # through training injection so these would otherwise sit open forever.
            open_requests = db.query(TrainerContinuationRequest).filter(
                TrainerContinuationRequest.trainee_id == trainee.id,
                TrainerContinuationRequest.status.in_(["pending", "accepted"]),
            ).all()
            for req in open_requests:
                req.status = "nullified"
                req.resolved_at = datetime.now(timezone.utc)

            warnings.append({
                "type": "graduation_notification",
                "message": (
                    f"Trainee {trainee.name} has completed {assignment_count} successful "
                    f"assignments and has been automatically graduated to Walker."
                ),
            })

    if warnings:
        db.commit()

    return warnings