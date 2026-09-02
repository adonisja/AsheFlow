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
    # ADR-289 D8 / ADR-290 D6: the DSP name as Amazon prints it on the BTR sheet
    # (e.g. "NYCD"). Distinct from `name`, which is the company's own legal or
    # trading name and need not match Amazon's label.
    #
    # Lives here rather than on CompanyConfig (where the ADR first placed it)
    # because its sibling `amazon_dsp_code` is here: the two are one fact about
    # the company's Amazon identity, and splitting them across tables would mean
    # a BTR import joins two rows to validate one sheet.
    #
    # Nullable: a company that has never seen a BTR sheet has no value to give,
    # and ADR-290 D6 treats "not configured" as "cannot validate" rather than
    # inventing a match.
    amazon_dsp_name  = Column(String(100),        nullable=True)
    timezone         = Column(String(64),         nullable=False, default="America/New_York")
    is_active        = Column(Boolean,            nullable=False, default=True, index=True)
    # ADR-280: is this tenant's data real?
    #
    #   live — real operational data. Seed scripts refuse it, fault injection
    #          refuses it, and analytics counts only this.
    #   seed — script-generated. Disposable: wipeable, re-generatable, and a
    #          legitimate fuzz/chaos target.
    #   demo — synthetic but CURATED, shown to prospects. Non-live like `seed`,
    #          but not something a chaos run may corrupt mid-demo.
    #
    # The default is `live` deliberately (D2). A company created by any path
    # that does not know about this column is treated as real, so the failure
    # mode is "a seeded tenant was mistakenly protected", never "a live tenant
    # was mistakenly wiped".
    #
    # Tenant-level rather than per-row (D1): every seeded row already descends
    # from a seeded company via company_id (ADR-064), so the tenancy boundary
    # already IS the provenance boundary. A per-row is_seed would be 14 models
    # and 14 places for a future write path to forget.
    data_class       = Column(String(10),         nullable=False, server_default="live", index=True)
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
    # ADR-264 — number of PHASES in the driver track, not calendar days. Floor of
    # 2: one teaching phase plus the observation phase is the minimum coherent
    # program. The last phase is always observation (D3).
    driver_training_days            = Column(Integer, nullable=True)   # default 5

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

    # ADR-356 — preference strength as a TARGET PROBABILITY. The dispatch_weight_*
    # and dispatch_*_bonus columns above are multipliers and flat adds; these are
    # "how often should this happen". Both sets exist during the transition: a
    # tenant's stored 0.70 is a MULTIPLIER, and reading it as a probability would
    # silently change dispatch for every company that ever tuned one. NULL here
    # means "use the platform default" (see preference_tiers.DEFAULT_TARGETS).
    dispatch_target_oneway_weak     = Column(Float, nullable=True)   # default 0.22
    dispatch_target_oneway_trainer  = Column(Float, nullable=True)   # default 0.25
    dispatch_target_oneway_captain  = Column(Float, nullable=True)   # default 0.28
    dispatch_target_oneway_driver   = Column(Float, nullable=True)   # default 0.33
    dispatch_target_mutual_weak     = Column(Float, nullable=True)   # default 0.45
    dispatch_target_mutual_lead_crew     = Column(Float, nullable=True)   # default 0.55
    dispatch_target_mutual_driver_trainer = Column(Float, nullable=True) # default 0.62
    dispatch_target_mutual_driver_captain = Column(Float, nullable=True) # default 0.68
    dispatch_target_tridirectional  = Column(Float, nullable=True)   # default 0.70
    dispatch_target_trio_plus       = Column(Float, nullable=True)   # default 0.80
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

    # ── Route-sort tuning (ADR-273) ───────────────────────────────────────────
    # These were hardcoded module constants in route_sort.py. Telemetry
    # (route_sort_runs / route_sort_daily) exists to tell an operator WHICH of
    # them to move, so they have to be movable without a deploy.
    #
    # ALL NULLABLE, and null means "use the code default" — deliberately NOT in
    # _REQUIRED_FIELDS. A null in that tuple 503s the entire tenant (see the
    # scorecard-target comment above), and a tenant that has never opened this
    # page must keep sorting on the defaults. Every read site resolves via
    # `cfg.x if cfg and cfg.x is not None else DEFAULT`.
    #
    # Seed priority (ADR-186 D3): W_TIME/W_DIFF sit above W_DENSE so a KNOWN
    # urgent/hard block outranks the densest unknown-easy one.
    sort_w_dense              = Column(Float(), nullable=True)   # default 1.0
    sort_w_time               = Column(Float(), nullable=True)   # default 1.5
    sort_w_diff               = Column(Float(), nullable=True)   # default 1.3
    sort_w_doorman            = Column(Float(), nullable=True)   # default 0.5 (subtracted)

    # Traversal guards (ADR-235). Both are inert when block centroids are
    # missing (_centroid_gap_m returns 0.0), so raising them cannot rescue a
    # coordinate-less run — see ADR-272 "Bug 3".
    sort_walk_budget_m        = Column(Float(), nullable=True)   # default 900.0
    sort_span_cap_m           = Column(Float(), nullable=True)   # default 700.0
    sort_max_consecutive_no_fit = Column(Integer(), nullable=True)  # default 2

    # F5 thin-block consolidation (ADR-197, reworked ADR-234). Retained under
    # ADR-272 but expected to fire far less once group-first lands.
    sort_f5_load_floor_hs     = Column(Integer(), nullable=True)  # default 6
    sort_f5_max_hops          = Column(Integer(), nullable=True)  # default 2
    sort_f5_walk_radius_km    = Column(Float(), nullable=True)    # default 0.8

    # Route assembly mode (ADR-272). Default null -> "block_completion".
    # "group_first" enables the ADR-272 branch. This is the switch Phase 3 flips.
    route_assembly_mode       = Column(String(20), nullable=True)

    # ── Manifest ingestion mode ───────────────────────────────────────────────
    ingestion_mode = Column(String(10), nullable=True)                 # "file" | "api"; default "file"

    # ── Operating mode (ADR-289) ──────────────────────────────────────────────
    # "full"      — Amazon package manifest available; the whole sort pipeline runs.
    # "workforce" — no package feed; package-path routers are gated off (404).
    #
    # nullable=False DELIBERATELY, unlike ingestion_mode / route_assembly_mode above.
    # A null here cannot distinguish "new company, not yet configured" from "config was
    # lost" — the two states ADR-283 showed a process cannot tell apart once they collapse
    # into one observable value. The mode decides whether ~40 endpoints exist, so it is
    # never inferred and never defaulted in code.
    #
    # SUPER ADMIN ONLY, and writable through exactly ONE endpoint:
    # PATCH /admin/companies/{id}/operating-mode, which carries the no-op 400, the
    # in-flight 409, the typed confirmation and the forced-override audit entry.
    #
    # It is in companies._GUARDED_FIELDS (not _SUPER_ADMIN_ONLY_FIELDS): both config
    # PATCH endpoints refuse it, the super-admin one included. Guards buried in a
    # generic field-setter are guards that get skipped.
    operating_mode = Column(String(20), nullable=False, server_default="workforce")

    # ── GeoClient address enrichment ─────────────────────────────────────────
    geoclient_borough = Column(String(30), nullable=True)              # e.g. "manhattan", "brooklyn", "queens"

    # ── Discord guild integration (optional — all nullable) ───────────────────
    discord_guild_id            = Column(BigInteger, nullable=True)
    discord_drivers_channel_id  = Column(BigInteger, nullable=True)
    discord_trainers_channel_id = Column(BigInteger, nullable=True)
    # ADR-256: the captains' room. Crew embeds post here alongside #trainers-chat
    # so the truck's route lead sees the crew they are leading.
    discord_captains_channel_id = Column(BigInteger, nullable=True)
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
        CheckConstraint("dispatch_target_oneway_weak IS NULL OR (dispatch_target_oneway_weak >= 0 AND dispatch_target_oneway_weak < 1)", name="ck_company_configs_target_oneway_weak"),
        CheckConstraint("dispatch_target_oneway_trainer IS NULL OR (dispatch_target_oneway_trainer >= 0 AND dispatch_target_oneway_trainer < 1)", name="ck_company_configs_target_oneway_trainer"),
        CheckConstraint("dispatch_target_oneway_captain IS NULL OR (dispatch_target_oneway_captain >= 0 AND dispatch_target_oneway_captain < 1)", name="ck_company_configs_target_oneway_captain"),
        CheckConstraint("dispatch_target_oneway_driver IS NULL OR (dispatch_target_oneway_driver >= 0 AND dispatch_target_oneway_driver < 1)", name="ck_company_configs_target_oneway_driver"),
        CheckConstraint("dispatch_target_mutual_weak IS NULL OR (dispatch_target_mutual_weak >= 0 AND dispatch_target_mutual_weak < 1)", name="ck_company_configs_target_mutual_weak"),
        CheckConstraint("dispatch_target_mutual_lead_crew IS NULL OR (dispatch_target_mutual_lead_crew >= 0 AND dispatch_target_mutual_lead_crew < 1)", name="ck_company_configs_target_mutual_lead_crew"),
        CheckConstraint("dispatch_target_mutual_driver_trainer IS NULL OR (dispatch_target_mutual_driver_trainer >= 0 AND dispatch_target_mutual_driver_trainer < 1)", name="ck_company_configs_target_mutual_driver_trainer"),
        CheckConstraint("dispatch_target_mutual_driver_captain IS NULL OR (dispatch_target_mutual_driver_captain >= 0 AND dispatch_target_mutual_driver_captain < 1)", name="ck_company_configs_target_mutual_driver_captain"),
        CheckConstraint("dispatch_target_tridirectional IS NULL OR (dispatch_target_tridirectional >= 0 AND dispatch_target_tridirectional < 1)", name="ck_company_configs_target_tridirectional"),
        CheckConstraint("dispatch_target_trio_plus IS NULL OR (dispatch_target_trio_plus >= 0 AND dispatch_target_trio_plus < 1)", name="ck_company_configs_target_trio_plus"),
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
