from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class LocationProfile(Base):
    """Persistent, crowdsourced building intelligence record for a specific block.

    Each record describes how a narrow address range on one side of a street operates
    for delivery purposes — its building type, the labor effort it demands, and any
    operational notes walkers need to know.

    This is REFERENCE DATA, not operational data. It lives above the daily delivery
    layer and informs how the routing algorithm distributes walkers across zones.
    It is distinct from LocationDifficultyFlag, which is ephemeral in-field feedback
    raised by a walker mid-route.

    --- block_key format ---
    10-number range + odds/evens side of the street:
        W_36_St_410s_odd   → 411, 413, 415, 417, 419
        W_36_St_410s_even  → 410, 412, 414, 416, 418
        8_Ave_500s_odd     → 501, 503, 505, 507, 509

    One record per (company_id, block_key, building_type). A single 10-number range
    that has mixed building types on the same side gets multiple records.

    --- building_type values ---
    mailroom        → bulk_drop    (photo of packages in room)
    receptionist    → bulk_drop    (get receptionist's name)
    walkup          → high_touch   (photo at front door)
    elevator        → standard     (photo at front door)
    biz_front       → standard     (photo at front door or receptionist name)
    biz_freight     → high_wait    (photo at front door or receptionist name)
    biz_security    → high_touch   (remind walker to bring ID)
    biz_loading_dock → bulk_drop   (photo at loading dock or mail clerk name)

    --- two independent verification lifecycles ---
    Building type:  pending → verified → locked → nominated → promoted | rejected
    Notes:          raw_notes (walker free text) → operational_note (captain structured) → note_verified

    --- promotion to the global library ---
    Once locked, a record becomes eligible for nomination to location_profile_library
    (AsheFlow's platform-wide building database available to all tenants). Nomination
    is automatic once the record is verified. A super admin approves or rejects the
    nomination. Automatic promotion also triggers when the same (block_key, building_type)
    is locked across 2+ independent companies.

    --- _name companion fields ---
    All employee FKs use ondelete="SET NULL". The _name companion field preserves the
    actor's name string independently so audit records remain readable after the employee
    is deleted from the system.
    """
    __tablename__ = "location_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "block_key", "building_type", name="uq_location_profiles_company_block_type"),
    )

    # 1. Identity — what block and building type this record describes
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    block_key     = Column(String(60),  nullable=False)   # e.g. "W_36_St_410s_odd"
    building_type = Column(String(30),  nullable=False)   # see building_type values above
    workload_class = Column(String(20), nullable=False)   # derived from building_type, stored for fast queries

    # 2. Building type lifecycle
    # Crowdsourced lock flow: pending → verified → locked
    # agreement_count increments each time a captain/driver verifies the building_type.
    # Once it reaches CompanyConfig.location_profile_lock_threshold (default 3), status → locked.
    # A conflicting submission on a locked record resets agreement_count and reopens review.
    building_type_status          = Column(String(20), server_default="pending")
    building_type_agreement_count = Column(Integer,    server_default="0")

    # 3. Promotion lifecycle
    # Once verified, a record is auto-nominated for the global library (location_profile_library).
    # A super admin approves or rejects the nomination.
    # null = not yet in the promotion pipeline
    # "nominated"  = queued for super admin review
    # "promoted"   = a copy now exists in location_profile_library
    # "rejected"   = super admin reviewed and declined (record stays locked and serves the company normally)
    nomination_status = Column(String(20), nullable=True)

    # 4. Notes lifecycle
    # Walker submits raw free text → captain converts to a structured operational_note.
    # Note verification is independent of building_type lock — a record can be locked
    # with an unverified note, or have a verified note while still pending building_type.
    raw_notes        = Column(Text,    nullable=True)
    operational_note = Column(Text,    nullable=True)
    note_verified    = Column(Boolean, server_default="false")
    note_verified_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    note_verified_by_name = Column(String(100), nullable=True)
    note_verified_at      = Column(DateTime(timezone=True), nullable=True)

    # 5. Submission audit — who first reported this building's characteristics
    # submitted_by is the walker with field knowledge. submitted_by_name is nullable=False
    # because someone always originates the report, even if the FK later goes null.
    submitted_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name = Column(String(100), nullable=False)
    submitted_at      = Column(DateTime(timezone=True), nullable=True)

    # 6. Building type verification audit — who approved the building_type
    verified_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    verified_by_name = Column(String(100), nullable=True)
    verified_at      = Column(DateTime(timezone=True), nullable=True)

    # 7. Record creation audit — who created the database row
    # created_by may differ from submitted_by: a captain bulk-entering known data before
    # day 1 is created_by but submitted_by is null. A walker filing a field report is both.
    created_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)