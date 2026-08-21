from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class BuildingProfileLibrary(Base):
    """AsheFlow-owned global compilation of verified address-level building intelligence.

    Tier 2 in the four-tier lookup chain. No company_id — this is a platform resource,
    not a tenant resource. Available read-only to all tenants as cold-start data when
    they have no locked BuildingProfile for a given address.

    Promotion triggers:
      Automatic: the same normalised_address reaches locked status in BuildingProfile
                 across 2+ independent companies.
      Manual:    super admin reviews a nominated BuildingProfile and approves it.

    Conflict handling:
      If a new company's locked BuildingProfile disagrees with a library record
      (different building_type), library_status → "conflict_pending" and
      last_conflict_at is stamped. Super admin reviews: update or keep.

    Access:
      All tenants can read active records (cold-start lookup).
      Only super admins can write (promote, resolve conflicts, deprecate).
      Super admin UUIDs are not in any tenant's employees table — no FK constraints.
    """
    __tablename__ = "building_profile_library"
    __table_args__ = (
        UniqueConstraint("normalised_address", name="uq_building_profile_library_address"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Address identity — global key, no company_id
    normalised_address  = Column(String(200), nullable=False)
    block_key           = Column(String(60),  nullable=False)   # denormalised for difficulty flag resolution

    # Delivery character
    building_type       = Column(String(30),  nullable=False)
    workload_class      = Column(String(20),  nullable=False)

    # Operational note — captain-verified tip promoted from the source company record
    # raw_notes are not promoted — only the structured operational_note is carried forward
    operational_note    = Column(Text, nullable=True)
    note_verified       = Column(Boolean, server_default="false", nullable=False)
    note_verified_by      = Column(UUID(as_uuid=True), nullable=True)   # super admin UUID, no FK to tenant table
    note_verified_by_name = Column(String(100), nullable=True)
    note_verified_at      = Column(DateTime(timezone=True), nullable=True)

    # Library lifecycle
    # "active"           = serves cold-start data to all tenants
    # "conflict_pending" = a tenant's locked record disagrees; super admin review required
    # "deprecated"       = superseded or inaccurate; no longer served
    library_status          = Column(String(20), server_default="active",  nullable=False)
    agreement_source_count  = Column(Integer,    server_default="0",       nullable=False)
    last_conflict_at        = Column(DateTime(timezone=True), nullable=True)

    # Promotion audit
    promoted_from_company_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=True)
    promoted_at               = Column(DateTime(timezone=True), nullable=True)
    promoted_by               = Column(UUID(as_uuid=True), nullable=True)   # null = automatic promotion
    promoted_by_name          = Column(String(100), nullable=True)

    # Operating hours — propagated from locked BuildingProfile on update
    opens_at            = Column(Time, nullable=True)
    closes_at           = Column(Time, nullable=True)
    break_start         = Column(Time, nullable=True)
    break_end           = Column(Time, nullable=True)
    days_open           = Column(ARRAY(String(10)), nullable=True)
    hours_timezone      = Column(String(50), nullable=True)
    hours_verified      = Column(Boolean, server_default="false", nullable=False)
    hours_verified_by      = Column(UUID(as_uuid=True), nullable=True)   # super admin UUID, no FK
    hours_verified_by_name = Column(String(100), nullable=True)
    hours_verified_at      = Column(DateTime(timezone=True), nullable=True)

    # Record audit
    created_by      = Column(UUID(as_uuid=True), nullable=True)
    created_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by      = Column(UUID(as_uuid=True), nullable=True)
    updated_by_name = Column(String(100), nullable=True)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
