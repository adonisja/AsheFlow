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
    Text, Time, UniqueConstraint,
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
# ADR-504 D8 [E]: "didn't find out" is an answer, and the default, so a blank is
# never read as "no".
TRISTATE = ("yes", "no", "unknown")
# [C]: hours by day group, each open / closed / didn't find out.
DAY_STATUS = ("open", "closed", "unknown")
DAY_GROUPS = ("weekday", "saturday", "sunday")
MAX_DELIVERY_POINTS = 3


class SurveyContributor(Base):
    """A named writer other than the owner (ADR-504 D1)."""
    __tablename__ = "survey_contributors"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The Cognito subject. Unique: one contributor row per account.
    cognito_sub         = Column(String(255), nullable=False, unique=True, index=True)
    # For the owner's own records of who signed. Never copied onto observations.
    display_name        = Column(String(100), nullable=False)
    # ADR-509. Set when the account was created in the product; NULL for rows
    # admitted by sub before that. The username is what Cognito's group calls
    # take; the email is what support needs to manage the account (ADR-509 D3).
    cognito_username    = Column(String(128), nullable=True)
    email               = Column(String(255), nullable=True)
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

    building_type    = Column(String(30), nullable=False)   # "unknown" for [F]
    # [F] A door on the city list that is not a delivery point (a gate, a second
    # entrance of the same building). Recorded so it doesn't look undone.
    not_a_delivery_point = Column(Boolean, nullable=False, server_default="false")
    security_desk    = Column(String(10), nullable=False, server_default="unknown")
    sign_in_required = Column(String(10), nullable=False, server_default="unknown")
    delivery_mode    = Column(String(20), nullable=True)
    floors           = Column(Integer, nullable=True)
    # [C] Receiving hours by day group. A status of "open" requires both times.
    weekday_status   = Column(String(10), nullable=False, server_default="unknown")
    weekday_open     = Column(Time, nullable=True)
    weekday_close    = Column(Time, nullable=True)
    saturday_status  = Column(String(10), nullable=False, server_default="unknown")
    saturday_open    = Column(Time, nullable=True)
    saturday_close   = Column(Time, nullable=True)
    sunday_status    = Column(String(10), nullable=False, server_default="unknown")
    sunday_open      = Column(Time, nullable=True)
    sunday_close     = Column(Time, nullable=True)
    break_start      = Column(Time, nullable=True)           # weekdays only
    break_end        = Column(Time, nullable=True)
    note             = Column(Text, nullable=True)           # scrubbed; never codes (D4)

    attestation   = Column(String(200), nullable=False)

    __table_args__ = (
        CheckConstraint(f"source IN {SOURCES}", name="ck_survey_obs_source"),
        CheckConstraint(f"security_desk IN {TRISTATE}", name="ck_survey_obs_security_desk"),
        CheckConstraint(f"sign_in_required IN {TRISTATE}", name="ck_survey_obs_sign_in"),
        *[CheckConstraint(
            f"{g}_status IN {DAY_STATUS} AND "
            f"({g}_status <> 'open' OR ({g}_open IS NOT NULL AND {g}_close IS NOT NULL))",
            name=f"ck_survey_obs_{g}_hours") for g in DAY_GROUPS],
        CheckConstraint(f"delivery_mode IS NULL OR delivery_mode IN {DELIVERY_MODES}",
                        name="ck_survey_obs_delivery_mode"),
        CheckConstraint("floors IS NULL OR (floors >= 1 AND floors <= 200)",
                        name="ck_survey_obs_floors"),
    )


class SurveyDeliveryPoint(Base):
    """[B] Where deliveries go. Up to three per observation, in order."""
    __tablename__ = "survey_delivery_points"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id = Column(UUID(as_uuid=True), ForeignKey("survey_observations.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    position       = Column(Integer, nullable=False)          # 1..3
    point          = Column(String(20), nullable=False)
    side           = Column(String(120), nullable=True)       # a street the block faces, or free text
    floor          = Column(Integer, nullable=True)
    which_packages = Column(String(120), nullable=True)       # "for the ground-floor business"

    __table_args__ = (
        CheckConstraint(f"point IN {DELIVERY_POINTS}", name="ck_survey_dp_point"),
        CheckConstraint(f"position >= 1 AND position <= {MAX_DELIVERY_POINTS}", name="ck_survey_dp_position"),
        CheckConstraint("floor IS NULL OR (floor >= -5 AND floor <= 200)", name="ck_survey_dp_floor"),
        UniqueConstraint("observation_id", "position", name="uq_survey_dp_position"),
    )


class SurveyReceivesFor(Base):
    """[A] Another door this receiving point serves. Always an address on the
    same city block, copied from the walk's snapshot, never typed."""
    __tablename__ = "survey_receives_for"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id = Column(UUID(as_uuid=True), ForeignKey("survey_observations.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    address        = Column(String(200), nullable=False)
    bin            = Column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("observation_id", "address", name="uq_survey_rf_address"),
    )
