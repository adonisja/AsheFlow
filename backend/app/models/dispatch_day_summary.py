import uuid
from sqlalchemy import Column, Date, DateTime, BigInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base


class DispatchDaySummary(Base):
    """Receipts for the two DAY-level Discord summary posts (ADR-327).

    ADR-295 gave the per-truck crew embed a `crew_embed_message_id` on
    TruckAssignment so a later change edits the standing roster instead of
    leaving a stale one. The two day-level summaries — the finalize table in
    #drivers-chat and the pairings post in #trainers-chat — never got the same
    treatment, so they could only ever append.

    That was nearly invisible while finalize was a whole-day operation: one
    finalize, one summary. ADR-325 made finalize per-truck, so a six-truck day
    produced six stacked summaries, each contradicting the last.

    Keyed per (company_id, date) rather than per truck, because that is the
    scope the messages actually describe — their titles have always said
    "Dispatch Finalized — <date>".
    """
    __tablename__ = "dispatch_day_summaries"
    __table_args__ = (
        # One row per company-day. The bot upserts on it, so the constraint is
        # what makes concurrent finalizes converge instead of racing to insert.
        UniqueConstraint("company_id", "date", name="uq_dispatch_day_summary_company_date"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    date       = Column(Date, nullable=False, index=True)

    # Discord snowflakes. BigInteger to match TruckAssignment.crew_embed_message_id
    # — an Integer column silently truncates a snowflake.
    drivers_summary_message_id  = Column(BigInteger, nullable=True)
    trainers_summary_message_id = Column(BigInteger, nullable=True)
    # ADR-332 D5 — the captains roster (ADR-256) is the same kind of
    # artifact: one standing message per day. Omitted from ADR-327 only
    # because the reported symptom was in the other two channels.
    captains_summary_message_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                        onupdate=func.now())
