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
    # ADR-256: the earlier confirmation deadline for roles expected at the AP before
    # the crew — driver and captain. A Time, read in the company's own timezone
    # (Company.timezone) like every other column here; a hardcoded 08:20 is wrong
    # for any tenant not on the seed company's clock. Null falls back to
    # checkin_close, which is what these roles used before this column existed.
    early_confirmation_deadline = Column(Time, nullable=True)

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
    # ADR-256: a captain's fan pull sits between driver and trainer — they lead the
    # truck's route work, the driver owns the vehicle and the day.
    dispatch_weight_captain         = Column(Float, nullable=True)   # default 0.50
    dispatch_weight_trainer         = Column(Float, nullable=True)   # default 0.25 (was 0.50)
    dispatch_weight_walker          = Column(Float, nullable=True)   # default 0.15 (was 0.30)

    # ── Captain truck familiarisation (ADR-256 D16) ───────────────────────────
    # A new captain holds one truck for this many dispatched days, then rotates to
    # a truck they have not yet completed. Familiarisation ends once every ACTIVE
    # truck has a completed row — after which the normal consecutive-day penalty
    # applies. Total cycle length is derived (active_trucks × this), never stored.
    captain_truck_rotation_days     = Column(Integer, nullable=True)  # default 5
    dispatch_mutual_bonus           = Column(Float, nullable=True)   # default 0.10
    dispatch_tridirectional_bonus   = Column(Float, nullable=True)   # default 0.20
    dispatch_consecutive_penalty    = Column(Float, nullable=True)   # default 0.05
    dispatch_weight_cap             = Column(Float, nullable=True)   # default 0.85

    # ── Walker rating anomaly detection ───────────────────────────────────────
    flag_threshold = Column(Float, nullable=True)   # default 1.0

    # ── Shift roll call ───────────────────────────────────────────────────────
    late_window_minutes = Column(Integer, nullable=True)    # default 20; minutes past the attendance reference before "late"
    # ADR-198: minutes past the attendance reference (max(shift_start, AP-established))
    # with no AP arrival before a crew member is NCNS. Nullable → default 60 in code.
    ncns_cutoff_minutes = Column(Integer, nullable=True)    # default 60

    # ── Driver mid-shift check-ins ────────────────────────────────────────────
    driver_checkin_count = Column(Integer, nullable=True)   # default 4

    # ── Route effort scoring tuning ───────────────────────────────────────────
    # Weights applied to time_weight and physical_weight per workload_class.
    # Default 0.5 each (equal contribution). Tuned per-company from field data.
    effort_time_factor     = Column(Float, nullable=True)   # default 0.5
    effort_physical_factor = Column(Float, nullable=True)   # default 0.5

    # ── Amazon scorecard tier targets (ADR-262) ───────────────────────────────
    # Per-DSP because Amazon sets several of these per station (DCR and DNR DPMO
    # explicitly), and our researched values come from third-party/UK guides that
    # are not authoritative for any given station. NULL means "no target
    # configured" — the UI shows Amazon's reported value with no pass/fail
    # judgement. Deliberately NOT in _REQUIRED_FIELDS: a DSP that has not yet read
    # its first Amazon card cannot supply these, and gating setup on them would
    # 503 the whole tenant. A missing threshold must never render as a failing one.
    #
    # Comparison DIRECTION is not stored here — it is domain truth, not tenant
    # configuration. See METRIC_DIRECTION in services/company_config.py.
    scorecard_dcr_target       = Column(Float,   nullable=True)  # %, higher better  (e.g. 99.0)
    scorecard_dnr_dpmo_target  = Column(Integer, nullable=True)  # DPMO, LOWER better (e.g. 950)
    scorecard_pod_target       = Column(Float,   nullable=True)  # %, higher better  (e.g. 97.0)
    scorecard_cc_target        = Column(Float,   nullable=True)  # %, higher better  (e.g. 98.0)
    scorecard_cdf_target       = Column(Float,   nullable=True)  # %, higher better  (e.g. 84.9)
    scorecard_dsb_dpmo_target  = Column(Integer, nullable=True)  # DPMO, LOWER better

    # Safety & Compliance — driver-only metrics (no walker analogue).
    scorecard_fico_target            = Column(Integer, nullable=True)  # 100–850, higher better (e.g. 800)
    scorecard_speeding_rate_target   = Column(Float,   nullable=True)  # per 100 trips, LOWER better (e.g. 10.0)
    scorecard_signsignal_rate_target = Column(Float,   nullable=True)  # per 100 trips, LOWER better (e.g. 15.0)
    scorecard_dvic_target            = Column(Float,   nullable=True)  # %, higher better (e.g. 95.0)

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
    # ADR-256: distinct guild roles. discord_role_captain previously held the
    # TRAINER role (Discord called trainers "Captain"); migration ff90779895f6
    # moved that value to discord_role_trainer and nulled this one.
    discord_role_trainer        = Column(BigInteger, nullable=True)
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
        CheckConstraint("dispatch_weight_captain   IS NULL OR (dispatch_weight_captain   BETWEEN 0 AND 1)", name="ck_company_configs_weight_captain"),
        CheckConstraint("captain_truck_rotation_days IS NULL OR captain_truck_rotation_days > 0", name="ck_company_configs_captain_rotation_days"),
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
