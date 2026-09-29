"""A scorecard row whose Transporter ID we do not yet recognise (ADR-476 D2).

THE FIRST SIGHT PROBLEM. Amazon's export identifies a person by Transporter ID,
which is stable and unambiguous -- and meaningless to us until somebody says
which of our employees it belongs to. That binding happens once, by a human,
using the `Delivery Associate` name Amazon supplies alongside it.

WHY A ROW RATHER THAN A GUESS. A fuzzy name match that is right 98% of the time
misroutes one row in fifty, every week, silently -- and a misrouted scorecard is
permanent: the person sees a stranger's speeding events, and by the time anyone
questions it there is no record of what the row originally said. A queue is an
annoyance; a wrong match is a data-integrity incident that also leaks one
person's performance to another.

So the payload is PARKED here in full rather than discarded. When the binding is
made the scorecard can be written without asking the operator to re-upload, and
until then nothing about that person is guessed at.
"""
import uuid

from sqlalchemy import (
    Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base


class ScorecardImportPending(Base):
    """One unresolved row from a bulk scorecard import."""

    __tablename__ = "scorecard_import_pending"
    __table_args__ = (
        # One parked row per (company, week, transporter). Re-uploading the same
        # file must not pile up duplicates for the operator to wade through --
        # a re-upload is a correction, not a second incident.
        UniqueConstraint("company_id", "week", "transporter_id",
                         name="uq_scorecard_import_pending_week_transporter"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    week           = Column(String(10), nullable=False, index=True)
    transporter_id = Column(String(32), nullable=False, index=True)
    # Amazon's name for this person, shown to the operator making the binding.
    # The ONLY thing that makes an opaque id resolvable by a human.
    da_name        = Column(String(200), nullable=True)
    # The parsed row, so resolving it needs no re-upload. Stored as the metric
    # payload we would have written, not the raw CSV line: the raw line carries
    # columns we deliberately do not keep.
    payload        = Column(JSONB, nullable=False)
    # Why it is here. Today always "unknown_transporter_id"; named rather than
    # implied so a second reason can be added without guessing at the first.
    reason         = Column(String(40), nullable=False,
                            default="unknown_transporter_id")
    note           = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now())
