from sqlalchemy import Column, Integer, DateTime, UniqueConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class BuildingProfileVerification(Base):
    """One person's confirmation of one BuildingProfile's building_type (ADR-276 D3).

    WHY A TABLE AND NOT A COUNTER
    -----------------------------
    `BuildingProfile.building_type_agreement_count` is a bare integer, and
    `verified_by` is OVERWRITTEN on each verify. So the model could not answer
    "has this person already confirmed?" — and nothing stopped one captain
    verifying twice to reach the threshold alone, or verifying their own
    submission.

    The unique constraint on (profile_id, employee_id) is the enforcement. It
    lives in the database rather than in the handler because that is the one
    place a future code path cannot forget it — the invariant this ADR exists to
    protect should not depend on remembering a check.

    It also recovers the audit trail: after the second confirmation the old
    `verified_by` was gone, so "who agreed this is a walkup" was unanswerable.

    WEIGHT IS STORED, NOT DERIVED
    -----------------------------
    A verifier's weight comes from their role at the moment they confirm
    (ADR-276 D1: captain/oversight = 2, driver = 1). Recomputing it later from
    `Employee.role` would silently re-score history when someone is promoted —
    a driver's old confirmation would become a captain's. The weight that
    applied is a fact about the confirmation, so it is written down.

    ROWS ARE DISCARDED ON DISAGREEMENT
    ----------------------------------
    ADR-276 D4: a confirmation that differs from the stored type resets the
    profile, and the prior rows go with it — they attested to a different fact
    and are not evidence for the new one.
    """
    __tablename__ = "building_profile_verifications"
    __table_args__ = (
        UniqueConstraint("profile_id", "employee_id",
                         name="uq_building_profile_verification_once"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    profile_id  = Column(
        UUID(as_uuid=True),
        ForeignKey("building_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SET NULL, not CASCADE: a departed employee's confirmation still counted,
    # and deleting it would silently drop a profile below its threshold.
    employee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Denormalised so the row survives employee deletion (ADR-221 redaction
    # applies to this the same as every other _name column).
    employee_name = Column(String(100), nullable=True)
    # The role that produced the weight — kept for "why was this worth 2?".
    employee_role = Column(String(30), nullable=True)
    weight        = Column(Integer, nullable=False)
    # The type being attested to. A row is only evidence FOR the value it
    # confirmed, which is what makes the D4 discard correct rather than lossy.
    building_type = Column(String(40), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
