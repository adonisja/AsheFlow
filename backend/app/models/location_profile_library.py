from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class LocationProfileLibrary(Base):
    """AsheFlow's platform-wide building intelligence database.

    This is the GLOBAL layer of the two-tier location intelligence system:

        Tier A (this model) — location_profile_library
            AsheFlow-owned. No company_id. Records are promoted here from
            tenant-scoped location_profiles once independently verified across
            multiple companies or approved by a super admin. Available read-only
            to all tenants, including companies entering a new delivery area
            for the first time (cold start data).

        Tier B — location_profiles
            Company-scoped. Each DSP populates their own records through walker
            submissions and captain verifications. Company records shadow library
            records during routing — if a company has their own locked record for
            a block, it takes precedence over the global entry.

    --- promotion triggers ---
    Automatic:  the same (block_key, building_type) reaches locked status in 2+
                independent companies. The system writes a new library record
                aggregating those sources.
    Manual:     a super admin reviews a nominated company record and approves it.
                Only super admins can write to this table.

    --- conflict handling ---
    If a new company's locked record disagrees with an existing library record
    (e.g., library says mailroom, new company locked receptionist), library_status
    flips to "conflict_pending" and last_conflict_at is stamped. A super admin
    reviews: if the building changed, the library record is updated and
    agreement_source_count resets. The company record is unaffected either way.

    --- tenant isolation ---
    This model intentionally has no company_id. It is a platform-level resource,
    not a tenant resource. Access is controlled at the router/service layer:
    all tenants can read, only super admins can write.

    --- no _name FK pattern ---
    Unlike tenant models, employee FKs here reference AsheFlow staff (super admins),
    not tenant employees. These are stored as plain UUIDs with _name companions but
    without FK constraints to the employees table, since super admins are not
    represented in any tenant's employee table.
    """
    __tablename__ = "location_profile_library"
    __table_args__ = (
        UniqueConstraint("block_key", "building_type", name="uq_location_profile_library_block_type"),
    )

    # 1. Identity — what block and building type this record describes
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    block_key     = Column(String(60),  nullable=False)   # e.g. "W_36_St_410s_odd"
    building_type = Column(String(30),  nullable=False)   # mailroom | receptionist | walkup | elevator | biz_front | biz_freight | biz_security | biz_loading_dock
    workload_class = Column(String(20), nullable=False)   # bulk_drop | high_touch | standard | high_wait

    # 2. Library lifecycle
    # "active"           = in use, serves as cold-start data for tenants entering this area
    # "conflict_pending" = a tenant's locked record disagrees; super admin review required
    # "deprecated"       = superseded or found to be inaccurate; no longer served to tenants
    library_status         = Column(String(20), server_default="active", nullable=False)
    agreement_source_count = Column(Integer,    server_default="0",      nullable=False)  # number of independent companies that confirmed this
    last_conflict_at       = Column(DateTime(timezone=True), nullable=True)               # stamped when library_status → conflict_pending

    # 3. Notes — structured operational note carried over from the promoting company record
    # raw_notes are not stored here — only the captain-verified structured version is promoted
    operational_note = Column(Text,    nullable=True)
    note_verified    = Column(Boolean, server_default="false", nullable=False)
    note_verified_by      = Column(UUID(as_uuid=True), nullable=True)   # super admin UUID, no FK to tenant employees table
    note_verified_by_name = Column(String(100), nullable=True)
    note_verified_at      = Column(DateTime(timezone=True), nullable=True)

    # 4. Promotion audit — which companies contributed and who promoted it
    # promoted_from_company_ids accumulates company_ids each time a new source agrees.
    # promoted_by is null for automatic promotions; set to super admin UUID for manual.
    promoted_from_company_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=True)
    promoted_at               = Column(DateTime(timezone=True), nullable=True)
    promoted_by               = Column(UUID(as_uuid=True), nullable=True)   # null = automatic promotion
    promoted_by_name          = Column(String(100), nullable=True)

    # 5. Record audit
    created_by      = Column(UUID(as_uuid=True), nullable=True)
    created_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by      = Column(UUID(as_uuid=True), nullable=True)
    updated_by_name = Column(String(100), nullable=True)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)