from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid import UUID
from datetime import date, datetime


class TrainingTaskBase(BaseModel):
    topic_title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
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
    trainer_comments: Optional[str] = Field(None, max_length=2000)
    manager_comments: Optional[str] = Field(None, max_length=2000)
    trainee_comments: Optional[str] = Field(None, max_length=2000)
    trainer_rating: Optional[int] = None
    is_locked: bool = False

class TrainingRecordCreate(TrainingRecordBase):
    trainee_id: UUID
    trainer_id: Optional[UUID] = None

class TrainingRecordResponse(TrainingRecordBase):
    id: UUID
    trainee_id: UUID
    trainer_id: Optional[UUID] = None
    # Persisted on submit but was never serialized — clients couldn't tell a
    # submitted day from an open one, so submit UIs re-rendered their forms
    # after every refetch.
    submitted_at: Optional[datetime] = None
    phase_closed: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    tasks: List[TrainingTaskResponse] = []

    # ── ADR-281: phase 0 (the ORE day) ──────────────────────────────────────
    # ore_completed_at is the DURABLE attestation; ore_certificate_key is not
    # serialized at all — an S3 key is an internal locator, and a client that
    # has one has a thing to guess at. The UI asks "is there a certificate?"
    # (has_certificate) and fetches a short-lived URL when a manager wants it.
    ore_completed_at: Optional[datetime] = None
    ore_certificate_expires_at: Optional[datetime] = None
    has_certificate: bool = False
    left_early: bool = False
    left_early_at: Optional[datetime] = None
    # True once a phase-1 record exists for the SAME date — the trainee stayed
    # after ORE. Set by the reader that knows about sibling records; the model
    # itself cannot see them.
    phase_one_started: bool = False

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _derive_has_certificate(self):
        """True only while the FILE is still retrievable.

        Derived rather than stored so the three states stay distinguishable:
          never uploaded  -> ore_completed_at None,     has_certificate False
          expired         -> ore_completed_at set,      has_certificate False
          available       -> ore_completed_at set,      has_certificate True
        """
        self.has_certificate = bool(self.ore_certificate_expires_at)
        return self

class TrainerCommentCreate(BaseModel):
    comments: str = Field(..., max_length=2000)

class ManagerCommentCreate(BaseModel):
    comments: str = Field(..., max_length=2000)

class TraineeReviewCreate(BaseModel):
    trainee_comments: str = Field(..., max_length=2000)
    trainer_rating: int = Field(..., ge=1, le=5)

class TraineeReassignRequest(BaseModel):
    trainee_id: UUID
    new_trainer_id: UUID
    target_date: date

class TaskUpdate(BaseModel):
    is_completed: bool
