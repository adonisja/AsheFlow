from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import RoleChecker, Pagination, get_current_user, get_caller_employee_optional, get_caller_employee
from app.database import get_db
from app.models.feedback import Feedback
from app.models.employee import Employee
from app.models.notification import Notification
from app.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackStatusUpdate

router = APIRouter(prefix="/feedback", tags=["feedback"])

allow_any_authenticated = get_current_user
allow_admin = RoleChecker(["admin"])

_VALID_STATUSES = {"new", "in_progress", "resolved"}

_TYPE_LABELS = {
    "bug":             "Bug Report",
    "feature_request": "Feature Request",
    "general":         "General Feedback",
}

@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    feedback: FeedbackCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_any_authenticated),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Submit new feedback. Requires a valid JWT — unauthenticated requests are rejected.

    Stamps employee_id automatically from the caller's employee record (if one
    exists — admin accounts have no employee row and will submit anonymously).
    Fans out a notification to all active admin employees.
    """
    db_feedback = Feedback(
        type=feedback.type,
        message=feedback.message,
        employee_id=caller.id if caller else None,
    )
    db.add(db_feedback)

    # Notify all active admins
    sender_name = caller.name if caller else "An employee"
    type_label  = _TYPE_LABELS.get(feedback.type, feedback.type.replace("_", " ").title())
    notif_message = (
        f"{type_label} submitted by {sender_name}: "
        f"{feedback.message[:120]}{'…' if len(feedback.message) > 120 else ''}"
    )
    company_id = caller.company_id if caller else None
    admins = db.query(Employee).filter(
        Employee.role == "admin",
        Employee.is_active == True,
        *([Employee.company_id == company_id] if company_id else []),
    ).all()
    for admin in admins:
        db.add(Notification(
            company_id=company_id,
            employee_id=admin.id,
            type="feedback_submitted",
            message=notif_message,
        ))

    db.commit()
    db.refresh(db_feedback)
    return db_feedback


@router.get("/", response_model=List[FeedbackResponse])
def get_all_feedback(
    pg: Pagination = Depends(),
    _: dict = Depends(allow_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Get all feedback (admin only). Joins employee name for display."""
    from sqlalchemy.orm import aliased
    from sqlalchemy import select

    rows = pg.apply(
        db.query(Feedback)
        .filter(Feedback.company_id == caller.company_id)
        .order_by(Feedback.created_at.desc())
    ).all()

    # Build employee_id → name map for the fetched page
    emp_ids = [r.employee_id for r in rows if r.employee_id]
    name_map: dict = {}
    if emp_ids:
        emps = db.query(Employee.id, Employee.name).filter(Employee.id.in_(emp_ids), Employee.company_id == caller.company_id).all()
        name_map = {str(e.id): e.name for e in emps}

    results = []
    for row in rows:
        data = FeedbackResponse.model_validate(row)
        data.sender_name = name_map.get(str(row.employee_id)) if row.employee_id else None
        results.append(data)
    return results


@router.patch("/{feedback_id}/status", response_model=FeedbackResponse)
def update_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusUpdate,
    _: dict = Depends(allow_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Update feedback status (admin only). Valid transitions: new → in_progress → resolved."""
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    record = db.query(Feedback).filter(Feedback.id == feedback_id, Feedback.company_id == caller.company_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Feedback record not found.")
    record.status = payload.status
    db.commit()
    db.refresh(record)
    return record
