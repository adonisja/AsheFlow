from sqlalchemy import Column, String, Boolean, DateTime, Integer, Float, Text, Time, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
import uuid
from app.models.base import Base


class BuildingProfile(Base):
    """Address-level delivery intelligence — source of truth for workload and operational data.

    Keyed on (company_id, normalised_address) where normalised_address is the
    GeoClient-normalised building address (e.g. "433 W 32 ST") — no unit, no name, not PII.

    Serves two consumers from the same record:
      Sort algorithm  → workload_class drives the weighted route effort score
      Walker UI       → building_type tag + operational_note surfaced at each stop

    building_type and workload_class are related but decoupled: workload_class is derived
    from building_type by default but a captain can override it independently when the
    default mapping doesn't match reality (e.g. a notoriously slow doorman → high_wait).

    Lifecycle: pending → verified → locked
      agreement_count increments each time a captain confirms the building_type.
      At 2+ agreements → verified; dispatch can then lock.
      When locked across 2+ independent companies → auto-nominated for BuildingProfileLibrary.

    Submission flow:
      Walker arrives at stop → normalised_address is already in frontend state from
      enriched manifest → walker selects building_type + optional raw_note and submits
      → captain sets operational_note from raw_note
      → captain verifies → agreement_count increments → locks at threshold
    """
    __tablename__ = "building_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "normalised_address", name="uq_building_profiles_company_address"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Address identity
    normalised_address  = Column(String(200), nullable=False)   # e.g. "433 W 32 ST"
    block_key           = Column(String(60),  nullable=False)   # denormalised for grouping + difficulty flag resolution

    # Delivery character — UI tag for the walker at the door
    building_type       = Column(String(30),  nullable=False)   # receptionist | walkup | elevator |
                                                                 # biz_freight | biz_security |
                                                                 # biz_loading_dock | mailroom | doorman

    # Routing signal — feeds the weighted route effort score at sort time
    # Derived from building_type by default; captain can override independently
    workload_class      = Column(String(20),  nullable=False)   # bulk_drop | standard | high_touch | high_wait

    # Operational notes — surfaced to walker at delivery time
    raw_note            = Column(Text, nullable=True)           # walker free-text submission
    operational_note    = Column(Text, nullable=True)           # captain-structured version
    note_verified       = Column(Boolean, server_default="false", nullable=False)

    # Building type verification lifecycle
    building_type_status          = Column(String(20), server_default="pending", nullable=False)
    building_type_agreement_count = Column(Integer,    server_default="0",       nullable=False)

    # Promotion pipeline (→ BuildingProfileLibrary)
    # null = not yet nominated | "nominated" = queued | "promoted" = in library | "rejected" = declined
    nomination_status   = Column(String(20), nullable=True)

    # Note verification audit
    note_verified_by        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    note_verified_by_name   = Column(String(100), nullable=True)
    note_verified_at        = Column(DateTime(timezone=True), nullable=True)

    # Submission audit — who first reported this building
    submitted_by        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name   = Column(String(100), nullable=False)
    submitted_at        = Column(DateTime(timezone=True), nullable=True)

    # Building type verification audit
    verified_by         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    verified_by_name    = Column(String(100), nullable=True)
    verified_at         = Column(DateTime(timezone=True), nullable=True)

    # Operating hours — feeds reattempt bundler and sort algorithm
    # hours_timezone defaults to company timezone when null
    opens_at            = Column(Time, nullable=True)
    closes_at           = Column(Time, nullable=True)
    break_start         = Column(Time, nullable=True)
    break_end           = Column(Time, nullable=True)
    days_open           = Column(ARRAY(String(10)), nullable=True)   # ["Mon","Tue","Wed","Thu","Fri"]
    hours_timezone      = Column(String(50), nullable=True)
    hours_verified      = Column(Boolean, server_default="false", nullable=False)
    hours_verified_by   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    hours_verified_by_name = Column(String(100), nullable=True)
    hours_verified_at   = Column(DateTime(timezone=True), nullable=True)

    # Row creation audit
    created_by          = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name     = Column(String(100), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
