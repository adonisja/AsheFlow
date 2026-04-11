from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import RoleChecker
from app.database import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])

@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    feedback: FeedbackCreate,
    db: Session = Depends(get_db)
):
    """Submit new feedback."""
    db_feedback = Feedback(**feedback.model_dump())
    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)
    return db_feedback

@router.get("/", response_model=List[FeedbackResponse])
def get_all_feedback(
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db)
):
    """Get all feedback (management/admin only)."""
    feedbacks = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return feedbacks
