import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, Float, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class GraduationQuizTemplate(Base):
    """
    Per-company question bank for the graduation quiz.

    Each company configures their own questions. MC questions are auto-scoreable;
    short-answer questions always go to under_review but may receive a preliminary
    auto_correct flag based on keyword matching.

    question_type: "multiple_choice" | "short_answer"
    choices: JSON list of option strings (MC only)
    correct_answer: exact match string for MC scoring; null for short_answer
    keywords: JSON list of strings; short_answer is considered preliminary-correct
              if the trainee's answer contains at least one keyword (case-insensitive)
    auto_scoreable: True for MC, False for short_answer
    """
    __tablename__ = "graduation_quiz_templates"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False)     # multiple_choice | short_answer
    choices       = Column(JSONB, nullable=True)           # list[str] for MC
    correct_answer = Column(Text, nullable=True)           # exact MC answer; null for short_answer
    is_mandatory  = Column(Boolean, nullable=False, default=True)
    auto_scoreable = Column(Boolean, nullable=False, default=False)
    keywords      = Column(JSONB, nullable=True)           # list[str] for short_answer preliminary
    display_order = Column(Integer, nullable=False, default=0)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class GraduationQuiz(Base):
    """
    One row per trainee quiz attempt.

    Lifecycle:
      pending_issue → issued (management sends to trainee)
                    → submitted (trainee submits answers)
                    → under_review (auto-scored, awaiting manager confirmation)
                    → passed | failed (manager confirms)

    On failed: manager can send for further training (generates a Phase 6
    remediation TrainingRecord via generate_quiz_remediation) and the next
    dispatch day after remediation closes will re-issue a Phase 5 quiz day.

    weak_topics: list of topic_titles from failed mandatory questions.
    Stored so the manager review screen and next trainer can target those areas.
    """
    __tablename__ = "graduation_quizzes"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    trainee_id          = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    issued_by           = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    training_record_id  = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="SET NULL"), nullable=True)
    attempt_number      = Column(Integer, nullable=False, default=1)
    issued_at           = Column(DateTime(timezone=True), nullable=True)
    submitted_at        = Column(DateTime(timezone=True), nullable=True)
    status              = Column(String(20), nullable=False, default="pending_issue")
    auto_score          = Column(Float, nullable=True)
    final_score         = Column(Float, nullable=True)
    passed              = Column(Boolean, nullable=True)
    manager_reviewed_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    manager_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    weak_topics         = Column(JSONB, nullable=True)    # list[str]
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())


class GraduationQuizResponse(Base):
    """
    One row per question per quiz attempt.

    auto_correct: set by the scoring engine.
      - MC: True/False based on exact match with correct_answer.
      - short_answer: True if at least one keyword matched (preliminary only);
        always goes to under_review regardless.
      - null if question has no auto_scoreable answer.

    manager_override: manager can flip auto_correct during review.
    override_note: optional per-question note from the manager.
    """
    __tablename__ = "graduation_quiz_responses"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    quiz_id          = Column(UUID(as_uuid=True), ForeignKey("graduation_quizzes.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id      = Column(UUID(as_uuid=True), ForeignKey("graduation_quiz_templates.id", ondelete="CASCADE"), nullable=False)
    answer_text      = Column(Text, nullable=True)
    auto_correct     = Column(Boolean, nullable=True)
    manager_override = Column(Boolean, nullable=True)
    override_note    = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
