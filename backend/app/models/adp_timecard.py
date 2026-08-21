from sqlalchemy import Column, String, Date, DateTime, Boolean, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base
import uuid


class ADPTimeCard(Base):
    __tablename__ = "adp_timecards"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_adp_timecards_employee_date"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    adp_associate_oid = Column(String(100), nullable=False)
    work_date = Column(Date, nullable=False, index=True)
    is_working_day = Column(Boolean, nullable=False, default=True)
    raw_payload = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())



class ADPTimeCardBreak(Base):
    """One meal/rest break as reported by ADP Workforce Now (ADR-233).

    Replaces ADPTimeCardSegment. RUN returned flat clock-in/clock-out pairs and
    AsheFlow *inferred* a break from the gap between them. Workforce Now reports
    breaks explicitly: teamTimeCards[].timeCards[].dayEntries[].timeEntries[].breaks[],
    described in ADP's own schema as "Meal times". Gap inference is wrong under
    WFN — it would treat any long non-break gap (split shift, unpaid downtime,
    mid-route clock-out) as a meal and propose it as a payroll correction.

    adp_entry_id is the parent timeEntry's entryID, not the break's own id. The
    write API (POST /events/time/v2/time-entries.modify) addresses a correction by
    that entryID, so it is stored as a first-class indexed column rather than left
    in raw_payload — the read is the only place it can be obtained.

    Both ids are opaque ADP strings ("8672975228284578|1", "456579", "-16"). Never
    parse or coerce them.
    """
    __tablename__ = "adp_timecard_breaks"
    __table_args__ = (
        UniqueConstraint("timecard_id", "adp_entry_id", "break_item_id", name="uq_adp_timecard_breaks_entry_item"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    timecard_id = Column(UUID(as_uuid=True), ForeignKey("adp_timecards.id", ondelete="CASCADE"), nullable=False, index=True)

    # timeEntries[].entryID — required by the write payload.
    adp_entry_id = Column(String(64), nullable=False, index=True)
    # breaks[].itemID — identifies the break within its entry.
    break_item_id = Column(String(64), nullable=True)

    # breaks[].startTime / endTime. ADP types these as timeType_v01 (bare string);
    # nullable because a break may be reported mid-shift with no end yet.
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)

    # breaks[].breakTypeCode.codeValue — 'meal', 'rest', ... Drives break
    # selection: a meal-typed break is preferred, subject to the duration gate.
    break_type_code = Column(String(40), nullable=True)
    # breaks[].breakStatus.codeValue
    break_status = Column(String(40), nullable=True)
    # breaks[].overrideTypeCode.codeValue — e.g. 'cancelmealdeduct', signalling
    # another system already adjusted this meal deduction.
    override_type_code = Column(String(40), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
