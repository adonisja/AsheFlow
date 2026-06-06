import uuid
from sqlalchemy import Column, Boolean, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class DriverSurvey(Base):
    """One survey per company per dispatch date, activated by management."""
    __tablename__ = "driver_surveys"
    __table_args__ = (
        UniqueConstraint("company_id", "date", name="uq_driver_survey_company_date"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    date       = Column(Date,               nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DriverSurveyResponse(Base):
    """One response per trainer/walker per survey.

    Auto-populated display fields (respondent name, email, driver name, truck name)
    are resolved at read time from employee + assignment data — not stored here.
    """
    __tablename__ = "driver_survey_responses"
    __table_args__ = (
        UniqueConstraint("survey_id", "respondent_id", name="uq_driver_survey_response_per_respondent"),
    )

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    survey_id            = Column(UUID(as_uuid=True), ForeignKey("driver_surveys.id",       ondelete="CASCADE"),   nullable=False, index=True)
    respondent_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id",            ondelete="CASCADE"),   nullable=False)
    truck_assignment_id  = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id",    ondelete="SET NULL"),  nullable=True)
    routes_organized     = Column(Boolean, nullable=False)
    anchor_point_location= Column(Boolean, nullable=False)
    supplies_ready       = Column(Boolean, nullable=False)
    driver_support       = Column(Boolean, nullable=False)
    notes                = Column(Text,    nullable=True)
    submitted_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
