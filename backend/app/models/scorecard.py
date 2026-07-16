import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base


class Scorecard(Base):
    """An official Amazon (NYCD) weekly scorecard, ingested by a manager and
    surfaced to the employee (ADR-204).

    scope='individual' → one DA's card (employee_id set); scope='company' → the
    station-wide weekly standing (employee_id NULL). `week` is the ISO label
    Amazon uses, e.g. "2026-W28". The metric rows are data-driven (ScorecardMetric)
    so new Amazon metrics need no schema change. Amazon-computed values are stored
    and displayed as-is; the cross-check (ADR-204 D) compares a subset against our
    own DeliveryStop/RTS data — the source_file_url is the uploaded scorecard image
    kept for reference/appeals.
    """
    __tablename__ = "scorecards"
    __table_args__ = (
        UniqueConstraint("company_id", "week", "scope", "employee_id", name="uq_scorecards_company_week_scope_employee"),
        CheckConstraint("scope IN ('individual', 'company')", name="ck_scorecards_scope"),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    week             = Column(String(10), nullable=False, index=True)          # e.g. "2026-W28"
    scope            = Column(String(20), nullable=False, default="individual") # individual | company
    employee_id      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True, index=True)
    overall_standing = Column(String(30), nullable=True)                        # e.g. "PLATINUM"
    source_file_url  = Column(Text, nullable=True)                              # uploaded scorecard image (data-URI or S3)
    entered_by       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    metrics = relationship(
        "ScorecardMetric", back_populates="scorecard",
        cascade="all, delete-orphan", order_by="ScorecardMetric.sort_order",
    )


class ScorecardMetric(Base):
    """One metric line on a scorecard (data-driven so the layout mirrors Amazon's
    without schema churn). `value` is stored as text — Amazon mixes numbers,
    percentages, and tier words (PLATINUM). `flag` is Amazon's per-row callout
    ('excellent' | 'needs_focus' | ...) and `tier` its tier badge when present."""
    __tablename__ = "scorecard_metrics"
    __table_args__ = (
        UniqueConstraint("scorecard_id", "key", name="uq_scorecard_metrics_scorecard_key"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scorecard_id = Column(UUID(as_uuid=True), ForeignKey("scorecards.id", ondelete="CASCADE"), nullable=False, index=True)
    key          = Column(String(50), nullable=False)      # stable machine key, e.g. "packages_delivered"
    label        = Column(String(100), nullable=False)     # display label, e.g. "Packages Delivered"
    value        = Column(String(50), nullable=False)      # "203" | "14492.7" | "100.0%" | "PLATINUM"
    unit         = Column(String(20), nullable=True)       # optional, e.g. "%", "DPMO"
    tier         = Column(String(30), nullable=True)       # optional tier word, e.g. "PLATINUM"
    flag         = Column(String(20), nullable=True)       # 'excellent' | 'needs_focus' | null
    sort_order   = Column(Integer, nullable=False, default=0)       # preserves Amazon's row order

    scorecard = relationship("Scorecard", back_populates="metrics")
