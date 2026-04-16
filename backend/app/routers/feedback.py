from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import RoleChecker, Pagination, get_current_user
from app.database import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackStatusUpdate

router = APIRouter(prefix="/feedback", tags=["feedback"])

allow_any_authenticated = get_current_user
allow_admin = RoleChecker(["admin"])

_VALID_STATUSES = {"new", "in_progress", "resolved"}

@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    feedback: FeedbackCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_any_authenticated),
):
    """Submit new feedback. Requires a valid JWT — unauthenticated requests are rejected."""
    db_feedback = Feedback(**feedback.model_dump())
    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)
    return db_feedback


@router.get("/", response_model=List[FeedbackResponse])
def get_all_feedback(
    pg: Pagination = Depends(),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Get all feedback (admin only)."""
    q = db.query(Feedback).order_by(Feedback.created_at.desc())
    return pg.apply(q).all()


@router.patch("/{feedback_id}/status", response_model=FeedbackResponse)
def update_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusUpdate,
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Update feedback status (admin only). Valid transitions: new → in_progress → resolved."""
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    record = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Feedback record not found.")
    record.status = payload.status
    db.commit()
    db.refresh(record)
    return record
