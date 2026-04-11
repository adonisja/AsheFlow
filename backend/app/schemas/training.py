from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import date, datetime


class TrainingTaskBase(BaseModel):
    topic_title: str
    description: Optional[str] = None
    is_completed: bool = False
    is_mandatory: bool = True
    is_training_debt: bool = False
    debt_age: int = 0
    is_escalated: bool = False

class TrainingTaskCreate(TrainingTaskBase):
    training_record_id: UUID

class TrainingTaskResponse(TrainingTaskBase):
    id: UUID
    training_record_id: UUID
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TrainingRecordBase(BaseModel):
    record_date: date
    current_day_number: int
    trainer_comments: Optional[str] = None
    manager_comments: Optional[str] = None
    trainee_comments: Optional[str] = None
    trainer_rating: Optional[int] = None
    is_locked: bool = False

class TrainingRecordCreate(TrainingRecordBase):
    trainee_id: UUID
    trainer_id: Optional[UUID] = None

class TrainingRecordResponse(TrainingRecordBase):
    id: UUID
    trainee_id: UUID
    trainer_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    tasks: List[TrainingTaskResponse] = []

    model_config = ConfigDict(from_attributes=True)

class TrainerCommentCreate(BaseModel):
    comments: str

class ManagerCommentCreate(BaseModel):
    comments: str

class TraineeReviewCreate(BaseModel):
    trainee_comments: str
    trainer_rating: int

class TraineeReassignRequest(BaseModel):
    trainee_id: UUID
    new_trainer_id: UUID
    target_date: date
