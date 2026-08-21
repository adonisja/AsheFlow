import uuid
from sqlalchemy import Column, String, Integer, Boolean, Date, Time, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class Incident(Base):
    """A field incident submitted by any field staff member.

    Supports multiple categories with category-specific nullable fields.
    Severity drives notification urgency: critical → alert, warning/info → standard.

    Attributes:
        reporter_id: FK to the submitting employee.
        truck_id: FK to the truck the reporter was assigned to today (auto-resolved, nullable if unassigned).
        date: Date of the incident (defaults to today).
        category: vehicle | injury | stolen_packages | customer_complaint | route_issue | crew_conduct | safety_hazard | other
        severity: info | warning | critical
        description: Free-text description / additional comments.
        photo_url: Optional base64 or future S3 URL.

        # Stolen packages
        incident_time: Time the theft occurred.
        packages_tba: Number of packages to be accounted for.
        incident_location: Street address or landmark.
        witness_name: Optional witness name.

        # Injury
        body_part_affected: Free text (e.g. "left ankle").
        medical_attention_required: Whether the employee needed or sought medical attention.

        resolved: Whether a manager/dispatch has closed the incident.
        resolved_by: FK to the employee who resolved it.
        resolved_at: Timestamp of resolution.
        created_at: Submission timestamp.
    """
    __tablename__ = "incidents"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reporter_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id      = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True)
    date          = Column(Date, nullable=False, index=True)
    category      = Column(String(30), nullable=False)
    severity      = Column(String(10), nullable=False, default="info")
    description   = Column(Text, nullable=False)
    photo_url     = Column(Text, nullable=True)

    # Stolen packages fields
    incident_time     = Column(Time, nullable=True)
    packages_tba      = Column(Integer, nullable=True)
    incident_location = Column(Text, nullable=True)
    # ADR-221: witness gets a mapped employee FK so the denormalized witness_name
    # is redactable on departure (was free-text only — the oversight). Nullable:
    # a witness may be a non-employee (e.g. a resident), in which case only
    # witness_name is set and it's treated as free text (not employee PII).
    witness_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    witness_name      = Column(Text, nullable=True)

    # Injury fields
    body_part_affected        = Column(Text, nullable=True)
    medical_attention_required = Column(Boolean, nullable=True)

    # Driver on the same truck — auto-resolved for non-driver reporters
    driver_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    driver_name = Column(String(100), nullable=True)

    resolved    = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name = Column(String(100), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
