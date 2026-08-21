"""Scorecard appeals (ADR-243).

A DSP disputes Amazon's weekly figures when its own records disagree — a DNR
counted against us that our RTS log shows was a customer-unavailable, for
instance. Money is attached to the outcome, so the dispute is a first-class
record rather than a note on the scorecard.

AsheFlow does NOT file with Amazon. A human does that in Amazon's portal; this
tracks preparation, filing, and result. The lifecycle deliberately stops at
"submitted" on our side and waits for a human to record what Amazon decided —
modelling a state we do not control would invent certainty we do not have.

Two tables, because Amazon can accept one contested metric and reject another in
the same appeal. A single row could not record that, and "which metrics do we win
on" is the question that makes the history worth keeping.
"""
from sqlalchemy import (
    Column, String, Text, Date, DateTime, Integer, Float, ForeignKey,
    CheckConstraint, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base
import uuid


# draft     — evidence being assembled; not yet filed with Amazon
# submitted — filed in Amazon's portal (submitted_at + amazon_reference set)
# won       — Amazon corrected the metric
# lost      — Amazon upheld its original figure
# withdrawn — we chose not to pursue it
APPEAL_STATUSES = ["draft", "submitted", "won", "lost", "withdrawn"]

# Terminal states cannot transition further; the 409 guard in the router keys off this.
APPEAL_TERMINAL_STATUSES = ["won", "lost", "withdrawn"]

# Per-line outcomes. `pending` until Amazon rules on that specific metric.
APPEAL_ITEM_OUTCOMES = ["pending", "accepted", "rejected"]


class ScorecardAppeal(Base):
    """One dispute against one scorecard.

    Unique on (company_id, scorecard_id) for non-terminal appeals is NOT enforced
    at the DB level: a week may legitimately be appealed twice if the first was
    withdrawn. The router enforces "only one open appeal per scorecard" instead,
    which expresses the real rule without blocking a second attempt.
    """
    __tablename__ = "scorecard_appeals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'won', 'lost', 'withdrawn')",
            name="ck_scorecard_appeals_status",
        ),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    scorecard_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scorecards.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Denormalised so an appeal remains readable if the scorecard is later
    # replaced by a corrected upload (the upsert path clears and rewrites metrics).
    week  = Column(String(10), nullable=False, index=True)
    scope = Column(String(20), nullable=False, default="company")   # company | individual
    # Set only for scope='individual'. SET NULL rather than CASCADE: an appeal is
    # a financial record and must survive the employee leaving.
    employee_id      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_name    = Column(String(100), nullable=True)

    status     = Column(String(20), nullable=False, default="draft", index=True)
    title      = Column(String(200), nullable=True)
    rationale  = Column(Text, nullable=True)      # the case, in our words

    # Filing — set when a human files it with Amazon
    submitted_at     = Column(DateTime(timezone=True), nullable=True)
    submitted_by     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name = Column(String(100), nullable=True)
    amazon_reference = Column(String(100), nullable=True)   # Amazon's case id, if issued

    # Outcome — set when Amazon responds
    resolved_at    = Column(DateTime(timezone=True), nullable=True)
    resolved_by    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name = Column(String(100), nullable=True)
    outcome_notes  = Column(Text, nullable=True)

    created_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship(
        "ScorecardAppealItem",
        back_populates="appeal",
        cascade="all, delete-orphan",
        order_by="ScorecardAppealItem.metric_key",
    )


class ScorecardAppealItem(Base):
    """One contested metric within an appeal.

    Values are snapshotted at draft time rather than read live from
    scorecard_metrics: re-uploading a corrected scorecard clears and rewrites
    those rows, which would silently rewrite the evidence an appeal was built on.
    A dispute record has to hold what was actually disputed.
    """
    __tablename__ = "scorecard_appeal_items"
    __table_args__ = (
        UniqueConstraint("appeal_id", "metric_key", name="uq_appeal_items_appeal_metric"),
        CheckConstraint(
            "outcome IN ('pending', 'accepted', 'rejected')",
            name="ck_scorecard_appeal_items_outcome",
        ),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stamped directly, not inherited via appeal_id — this table must be usable
    # as a query root ("which metrics do we win most often, company-wide?")
    # without a join being the only thing standing between it and a cross-tenant
    # leak (CLAUDE.md Dimension 1, the lesson from migration 380b54c07d88).
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    appeal_id  = Column(
        UUID(as_uuid=True),
        ForeignKey("scorecard_appeals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    metric_key   = Column(String(50), nullable=False)    # matches ScorecardMetric.key
    metric_label = Column(String(100), nullable=False)

    # Snapshot of the disagreement at the time the appeal was drafted.
    amazon_value = Column(String(50), nullable=True)     # as displayed, e.g. "1250.0"
    our_value    = Column(String(50), nullable=True)
    delta        = Column(Float, nullable=True)          # amazon - ours, when both numeric

    # Supporting records pulled from our own data (RTS reasons, stop counts).
    # JSONB rather than an FK table: the shape varies per metric, and the appeal
    # needs the evidence AS IT WAS, not a live join that can drift.
    evidence     = Column(JSONB, nullable=True)
    claim        = Column(Text, nullable=True)           # what we assert for this metric

    outcome       = Column(String(20), nullable=False, default="pending", index=True)
    outcome_notes = Column(Text, nullable=True)
    # Amazon's corrected figure, when they accept the appeal.
    corrected_value = Column(String(50), nullable=True)

    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    appeal = relationship("ScorecardAppeal", back_populates="items")
