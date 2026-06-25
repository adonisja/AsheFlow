from sqlalchemy import Column, String, Boolean, DateTime, Integer, Float, Time, ForeignKey, BigInteger, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime, timezone


class Company(Base):
    """A DSP company onboarded to AsheFlow.

    One row per company. All tenant-scoped tables reference this via company_id.
    """
    __tablename__ = "companies"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name             = Column(String(255),        nullable=False)
    slug             = Column(String(100),        nullable=False, unique=True, index=True)
    amazon_dsp_code  = Column(String(20),         nullable=True)
    timezone         = Column(String(64),         nullable=False, default="America/New_York")
    is_active        = Column(Boolean,            nullable=False, default=True, index=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    config = relationship("CompanyConfig", back_populates="company", uselist=False)
    zones  = relationship("CompanyZone",   back_populates="company")


class CompanyConfig(Base):
    """All configurable operational values for a company.

    One row per company. NULL means "not yet configured" — the backend
    falls back to the hardcoded defaults in constants.py until set.
    """
    __tablename__ = "company_configs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, unique=True, index=True)

    # ── Shift timing ──────────────────────────────────────────────────────────
    shift_start    = Column(Time, nullable=True)   # e.g. 07:00
    shift_end      = Column(Time, nullable=True)   # e.g. 18:00
    checkin_open   = Column(Time, nullable=True)   # earliest accepted check-in
    checkin_close  = Column(Time, nullable=True)   # latest accepted check-in
    dispatch_confirmation_cutoff = Column(Time, nullable=True)  # default 09:00 — pending notifications expire after this

    # ── Walker rating window ──────────────────────────────────────────────────
    # Hours after driver departure that walker ratings are accepted.
    rating_window_hours = Column(Integer, nullable=True)   # default 6

    # ── Account lifecycle ─────────────────────────────────────────────────────
    invite_expiry_days = Column(Integer, nullable=True)    # default 7

    # ── Training rules ────────────────────────────────────────────────────────
    graduation_assignments          = Column(Integer, nullable=True)   # default 5
    debt_escalation_threshold       = Column(Integer, nullable=True)   # default 3
    phase4_pass_score               = Column(Float,   nullable=True)   # default 90.0
    underperforming_trainer_threshold = Column(Integer, nullable=True) # default 3
    max_training_phase              = Column(Integer, nullable=True)   # default 4

    # ── Dispatch algorithm weights ────────────────────────────────────────────
    dispatch_weight_driver          = Column(Float, nullable=True)   # default 0.70
    dispatch_weight_trainer         = Column(Float, nullable=True)   # default 0.50
    dispatch_weight_walker          = Column(Float, nullable=True)   # default 0.30
    dispatch_mutual_bonus           = Column(Float, nullable=True)   # default 0.10
    dispatch_tridirectional_bonus   = Column(Float, nullable=True)   # default 0.20
    dispatch_consecutive_penalty    = Column(Float, nullable=True)   # default 0.05
    dispatch_weight_cap             = Column(Float, nullable=True)   # default 0.85

    # ── Walker rating anomaly detection ───────────────────────────────────────
    flag_threshold = Column(Float, nullable=True)   # default 1.0

    # ── Driver mid-shift check-ins ────────────────────────────────────────────
    driver_checkin_count = Column(Integer, nullable=True)   # default 4

    # ── Tier 1 tote verification (DBSCAN + classification thresholds) ─────────
    tier1_dbscan_eps           = Column(Float,   nullable=True)   # default 0.015 degrees (~1 mile)
    tier1_dbscan_min_samples   = Column(Integer, nullable=True)   # default 30
    tier1_small_tote_cutoff    = Column(Integer, nullable=True)   # default 10 packages
    tier1_small_stray_max      = Column(Integer, nullable=True)   # default 1 (count)
    tier1_small_uncertain_max  = Column(Integer, nullable=True)   # default 3 (count)
    tier1_stray_pct            = Column(Float,   nullable=True)   # default 0.10
    tier1_uncertain_pct        = Column(Float,   nullable=True)   # default 0.40

    # ── Route effort scoring tuning ───────────────────────────────────────────
    # Weights applied to time_weight and physical_weight per workload_class.
    # Default 0.5 each (equal contribution). Tuned per-company from field data.
    effort_time_factor     = Column(Float, nullable=True)   # default 0.5
    effort_physical_factor = Column(Float, nullable=True)   # default 0.5

    # ── Manifest ingestion mode ───────────────────────────────────────────────
    ingestion_mode = Column(String(10), nullable=True)                 # "file" | "api"; default "file"

    # ── GeoClient address enrichment ─────────────────────────────────────────
    geoclient_borough = Column(String(30), nullable=True)              # e.g. "manhattan", "brooklyn", "queens"

    # ── Discord guild integration (optional — all nullable) ───────────────────
    discord_guild_id            = Column(BigInteger, nullable=True)
    discord_drivers_channel_id  = Column(BigInteger, nullable=True)
    discord_trainers_channel_id = Column(BigInteger, nullable=True)
    discord_general_channel_id  = Column(BigInteger, nullable=True)
    discord_invite_channel_id   = Column(BigInteger, nullable=True)
    discord_role_admin          = Column(BigInteger, nullable=True)
    discord_role_manager        = Column(BigInteger, nullable=True)
    discord_role_asheflow       = Column(BigInteger, nullable=True)
    discord_role_bot            = Column(BigInteger, nullable=True)
    discord_role_dispatch       = Column(BigInteger, nullable=True)
    discord_role_driver         = Column(BigInteger, nullable=True)
    discord_role_captain        = Column(BigInteger, nullable=True)
    discord_role_walker         = Column(BigInteger, nullable=True)

    # ── ADP payroll correction escalation thresholds ─────────────────
    adp_urgent_correction_day = Column(Integer, nullable=False, default=5)
    adp_mandatory_correction_day = Column(Integer, nullable=False, default=6)
    adp_mandatory_correction_hour = Column(Integer, nullable=False, default=0)

    # True once the admin has completed the initial setup form.
    # Every protected endpoint checks this via require_configured.
    is_configured = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("dispatch_weight_driver    IS NULL OR (dispatch_weight_driver    BETWEEN 0 AND 1)", name="ck_company_configs_weight_driver"),
        CheckConstraint("dispatch_weight_trainer   IS NULL OR (dispatch_weight_trainer   BETWEEN 0 AND 1)", name="ck_company_configs_weight_trainer"),
        CheckConstraint("dispatch_weight_walker    IS NULL OR (dispatch_weight_walker    BETWEEN 0 AND 1)", name="ck_company_configs_weight_walker"),
        CheckConstraint("dispatch_mutual_bonus     IS NULL OR (dispatch_mutual_bonus     BETWEEN 0 AND 1)", name="ck_company_configs_mutual_bonus"),
        CheckConstraint("dispatch_tridirectional_bonus IS NULL OR (dispatch_tridirectional_bonus BETWEEN 0 AND 1)", name="ck_company_configs_tridirectional_bonus"),
        CheckConstraint("dispatch_consecutive_penalty IS NULL OR (dispatch_consecutive_penalty  BETWEEN 0 AND 1)", name="ck_company_configs_consecutive_penalty"),
        CheckConstraint("dispatch_weight_cap       IS NULL OR (dispatch_weight_cap       BETWEEN 0 AND 1)", name="ck_company_configs_weight_cap"),
    )

    company = relationship("Company", back_populates="config")


class CompanyZone(Base):
    """A geographic zone assigned to a company's DSP operation.

    Zones can be nested: a top-level zone covers the full DSP area;
    child zones (parent_zone_id set) are subsections used for route mapping.
    bounds stores a GeoJSON Polygon object.
    """
    __tablename__ = "company_zones"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id     = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    parent_zone_id = Column(UUID(as_uuid=True), nullable=True,  index=True)
    name           = Column(String(255),        nullable=False)
    bounds         = Column(JSONB,              nullable=True)   # GeoJSON Polygon
    is_active      = Column(Boolean,            nullable=False, default=True)
    created_at     = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="zones")
