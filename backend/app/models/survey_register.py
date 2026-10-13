"""The survey register: building knowledge kept OUTSIDE any tenant (ADR-504).

Three tables, no `company_id` on any of them. This is the owner's own dataset,
built from observations made outside any carrier's services, so it belongs to no
tenant. That absence is the point, not an omission (ADR-504 D1).

    survey_contributors   who, besides the owner, may write. Admitted after a
                          signed contributor agreement; revocable.
    survey_walks          one block walked by one writer: the protocol
                          confirmations, and a SNAPSHOT of the city's address
                          list for that block (D3: doors come from public data).
    survey_observations   append-only facts about one door on a walk. A
                          re-visit is a new observation, never an edit, so every
                          fact keeps who saw it, when, and how (D5).

Nothing here is ever written from tenant data (D6); a drift test enforces it.
"""
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String,
    Text, Time,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.models.base import Base

# D5: where a fact came from. The ROLE that answered, never the person's name.
SOURCES = ("observed", "front_desk", "mailroom", "security")
# Where deliveries are taken in. The most-written note in the old form (ADR-504
# D6 analysis: "entrance", "service", "located") made structured.
DELIVERY_POINTS = ("main_entrance", "service_entrance", "loading_dock", "mailroom", "front_desk")
DELIVERY_MODES = ("each_unit", "one_drop_point")


class SurveyContributor(Base):
    """A named writer other than the owner (ADR-504 D1)."""
    __tablename__ = "survey_contributors"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The Cognito subject. Unique: one contributor row per account.
    cognito_sub         = Column(String(255), nullable=False, unique=True, index=True)
    # For the owner's own records of who signed. Never copied onto observations.
    display_name        = Column(String(100), nullable=False)
    agreement_version   = Column(String(20), nullable=False)
    agreement_signed_on = Column(Date, nullable=False)
    admitted_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    admitted_by         = Column(String(64), nullable=True)      # super admin id; no Employee FK
    revoked_at          = Column(DateTime(timezone=True), nullable=True)


class SurveyWalk(Base):
    """One block, walked once, under the D2 protocol."""
    __tablename__ = "survey_walks"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    writer_sub     = Column(String(255), nullable=False, index=True)
    block_key      = Column(String(100), nullable=False, index=True)
    street         = Column(String(120), nullable=False)
    # D3. The city's addresses for this block, as fetched when the walk began:
    # [{"address", "bin", "lat", "lng"}]. Public data (NYC AddressPoint), and the
    # proof that the doors were chosen from it rather than from deliveries.
    addresses      = Column(JSONB, nullable=False)
    source_dataset = Column(String(20), nullable=False)
    fetched_at     = Column(DateTime(timezone=True), nullable=False)
    # D2. Each must be TRUE for the walk to exist (also a DB CHECK).
    attest_off_shift = Column(Boolean, nullable=False)
    attest_unbranded = Column(Boolean, nullable=False)
    attest_as_self   = Column(Boolean, nullable=False)
    started_at     = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at      = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("attest_off_shift AND attest_unbranded AND attest_as_self",
                        name="ck_survey_walk_attested"),
    )


class SurveyObservation(Base):
    """What one writer learned about one door on one walk (ADR-504 D4, D5)."""
    __tablename__ = "survey_observations"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: an observation without its walk has lost its provenance.
    walk_id       = Column(UUID(as_uuid=True), ForeignKey("survey_walks.id", ondelete="RESTRICT"),
                           nullable=False, index=True)
    writer_sub    = Column(String(255), nullable=False, index=True)
    address       = Column(String(200), nullable=False)
    bin           = Column(String(20), nullable=True, index=True)
    observed_on   = Column(Date, nullable=False)
    observed_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source        = Column(String(20), nullable=False)

    building_type    = Column(String(30), nullable=False)
    delivery_point   = Column(String(20), nullable=True)
    entrance_side    = Column(String(120), nullable=True)   # "on 33rd St", "rear, via the alley"
    security_desk    = Column(Boolean, nullable=True)
    sign_in_required = Column(Boolean, nullable=True)
    delivery_mode    = Column(String(20), nullable=True)
    floors           = Column(Integer, nullable=True)
    opens_at         = Column(Time, nullable=True)
    closes_at        = Column(Time, nullable=True)
    break_start      = Column(Time, nullable=True)
    break_end        = Column(Time, nullable=True)
    note             = Column(Text, nullable=True)           # scrubbed; never codes (D4)

    attestation   = Column(String(200), nullable=False)

    __table_args__ = (
        CheckConstraint(f"source IN {SOURCES}", name="ck_survey_obs_source"),
        CheckConstraint(f"delivery_point IS NULL OR delivery_point IN {DELIVERY_POINTS}",
                        name="ck_survey_obs_delivery_point"),
        CheckConstraint(f"delivery_mode IS NULL OR delivery_mode IN {DELIVERY_MODES}",
                        name="ck_survey_obs_delivery_mode"),
        CheckConstraint("floors IS NULL OR (floors >= 1 AND floors <= 200)",
                        name="ck_survey_obs_floors"),
    )
