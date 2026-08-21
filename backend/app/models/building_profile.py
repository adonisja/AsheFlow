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

    # ADR-277 D1: address resolution. What a human types is not what the
    # manifest carries — '433 West 32nd Street', '433 W 32 St' and '433 w 32 st'
    # all derive block_key W_32_St_400 but are three distinct rows under the
    # (company_id, normalised_address) unique constraint, and routing (which
    # looks up BY normalised address) matches none of them.
    #
    # So the submitter's text lands here verbatim, a Celery task resolves it,
    # and on success normalised_address is REWRITTEN to GeoClient's canonical
    # form. The typed string is not kept alongside it: the canonical form IS
    # the address, and keeping both would reintroduce the ambiguity this
    # removes. raw_note already covers anything the submitter wants to say in
    # their own words.
    #
    #   pending  — accepted, GeoClient not yet consulted
    #   resolved — canonicalised
    #   rejected — no match; geo_grc says why, and the submitter can edit+retry
    #
    # A `rejected` row is EXCLUDED from every routing lookup. Without that it
    # sits in the table looking like intelligence while matching no stop —
    # indistinguishable from a building nobody has visited.
    address_status      = Column(String(20), nullable=False, server_default="pending", index=True)
    geo_grc             = Column(String(10), nullable=True)     # Geosupport return code on rejection
    geo_message         = Column(String(200), nullable=True)    # human-readable reason, shown on the retry form

    # ADR-277 D2 / ADR-279: GeoClient output worth keeping.
    # lat/lng give the truck page proximity sorting and initial_anchor a sane
    # default. segment_id is the structural one: paired with
    # DeliveryStop.segment_id it survives the ADR-219 48h address nulling, so a
    # stop can still find its building past the window. Public street topology,
    # not PII — no house number, no TBA (see StreetSegment).
    lat                 = Column(Float, nullable=True)
    lng                 = Column(Float, nullable=True)
    segment_id          = Column(String(32), nullable=True, index=True)

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

    # Troublesome decaying score (ADR-218). Bumped per RTS (weighted by type),
    # decayed nightly (~30-day half-life). Lets the company-wide "troublesome
    # buildings" list be read off the building instead of retaining delivery rows.
    troublesome_score            = Column(Float, server_default="0", nullable=False)
    troublesome_last_incident_at = Column(DateTime(timezone=True), nullable=True)
    troublesome_resolved_at      = Column(DateTime(timezone=True), nullable=True)

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

    # Initial anchor point — the default starting location for deliveries in this building's zone.
    # Null until dispatch explicitly sets it. Feeds Field Ops AP workflow (fallback suggestion)
    # and the sort pipeline (anchor hint for trucks with no anchor or zone history).
    initial_anchor_lat  = Column(Float, nullable=True)
    initial_anchor_lng  = Column(Float, nullable=True)
    initial_anchor_note = Column(String(200), nullable=True)   # brief label e.g. "Corner of 9th Ave"
    initial_anchor_set_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    initial_anchor_set_by_name = Column(String(100), nullable=True)
    initial_anchor_set_at      = Column(DateTime(timezone=True), nullable=True)

    # Row creation audit
    created_by          = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name     = Column(String(100), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
