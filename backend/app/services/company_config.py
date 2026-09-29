"""
company_config.py — per-company configuration resolver.

Call get_company_config(db, company_id) to get a ResolvedConfig whose
required fields are guaranteed non-null.  Optional fields (shift timing,
driver_checkin_count) may be None — callers that need them must handle None.

Raises HTTPException 503 if the company has not completed initial setup.
Raises HTTPException 500 if the config row is missing entirely (provisioning bug).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.company import CompanyConfig


# ---------------------------------------------------------------------------
# Platform defaults — used ONLY by the provisioning path to seed a new
# CompanyConfig row.  Never used as silent fallbacks in get_company_config.
# ---------------------------------------------------------------------------

PLATFORM_DEFAULTS: dict = {
    "rating_window_hours":              6,
    "invite_expiry_days":               7,
    "graduation_assignments":           5,
    "debt_escalation_threshold":        3,
    "phase4_pass_score":                90.0,
    "underperforming_trainer_threshold": 3,
    "max_training_phase":               4,
    "driver_training_days":             5,   # ADR-264 — phases, not days
    "dispatch_weight_driver":           0.70,
    # ADR-256: captain between driver and trainer; trainer and walker drop because a
    # trainer no longer holds operational context on the truck. Existing tenants with
    # a STORED value keep it — a platform default only covers the unset case, so the
    # migration backfills the old 0.50/0.30 explicitly rather than silently reweighting
    # a live dispatch.
    "dispatch_weight_captain":          0.50,
    "dispatch_weight_trainer":          0.25,
    "dispatch_weight_walker":           0.15,
    "captain_truck_rotation_days":      5,
    "dispatch_mutual_bonus":            0.10,
    "dispatch_tridirectional_bonus":    0.20,
    # ADR-356 — target probabilities. Deliberately NOT in _REQUIRED_FIELDS: an
    # existing tenant must keep resolving to NULL so it falls back to these
    # platform defaults rather than inheriting a stale multiplier.
    "dispatch_target_oneway_weak":      0.22,
    "dispatch_target_oneway_trainer":   0.25,
    "dispatch_target_oneway_captain":   0.28,
    "dispatch_target_oneway_driver":    0.33,
    "dispatch_target_mutual_weak":      0.45,
    "dispatch_target_mutual_lead_crew":      0.55,
    "dispatch_target_mutual_driver_trainer": 0.60,
    "dispatch_target_mutual_driver_captain": 0.65,
    "dispatch_target_tridirectional":   0.80,
    "dispatch_target_trio_plus":        0.88,
    "dispatch_consecutive_penalty":     0.05,
    "dispatch_weight_cap":              0.85,
    "flag_threshold":                   1.0,
    "driver_checkin_count":             4,
}

_REQUIRED_FIELDS: tuple[str, ...] = (
    "rating_window_hours",
    "invite_expiry_days",
    "graduation_assignments",
    "debt_escalation_threshold",
    "phase4_pass_score",
    "underperforming_trainer_threshold",
    "max_training_phase",
    "dispatch_weight_driver",
    "dispatch_weight_trainer",
    "dispatch_weight_walker",
    "dispatch_mutual_bonus",
    "dispatch_tridirectional_bonus",
    "dispatch_consecutive_penalty",
    "dispatch_weight_cap",
    "flag_threshold",
)


# ---------------------------------------------------------------------------
# Scorecard metric direction (ADR-262)
#
# Which way "good" lies is a property of the METRIC, not of the tenant. A DSP
# may configure what its target is; it may not configure whether higher or lower
# passes. Keeping direction here rather than in CompanyConfig is what stops a
# generic `value >= target` from silently inverting every DPMO metric — an
# inverted comparison does not raise, does not fail typing, and reports an
# excellent DNR DPMO of 400 as failing a <=950 target.
#
# Keys are the metric keys used by ScorecardMetric.key (ADR-204).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Metric registry (ADR-473)
# ---------------------------------------------------------------------------
#
# REPLACES METRIC_DIRECTION + METRIC_TARGET_FIELD, two hand-maintained dicts
# that had to agree with each other AND with ten column definitions. Five of the
# ten disagreed with Amazon's own metric guides -- two defect rates modelled as
# percentages where higher passes, a completion rate measuring something else, a
# metric that is not scored at all, and one folded inside another.
#
# Direction and unit now travel with the metric instead of being asserted in a
# column comment. A stored target (CompanyMetricTarget) carries its own copy, so
# this registry is the DEFAULT shape for a known key, not the authority at
# comparison time -- `meets_target` reads the row.
#
# NO THRESHOLD VALUES LIVE HERE (ADR-473 D5). Amazon revises them, they are
# commercially sensitive, and the DSP Program Agreement obliges the tenant to
# protect them. Shapes are ours; numbers are the tenant's.

METRIC_SHAPES: dict[str, dict[str, str]] = {
    # Quality
    "pod":              {"direction": "higher", "unit": "percent"},
    "dsb_dpmo":         {"direction": "lower",  "unit": "dpmo"},
    "cdf_dpmo":         {"direction": "lower",  "unit": "dpmo"},
    "dc_dpmo":          {"direction": "lower",  "unit": "dpmo"},
    # Safety. The three added here are roughly half the safety score between
    # them, and had no field at all -- a tenant tuning only speeding and
    # sign/signal was tuning the minority of it.
    "fico":             {"direction": "higher", "unit": "score"},
    "speeding_rate":    {"direction": "lower",  "unit": "rate_per_100"},
    "signsignal_rate":  {"direction": "lower",  "unit": "rate_per_100"},
    "seatbelt_rate":    {"direction": "lower",  "unit": "rate_per_100"},
    "distractions_rate": {"direction": "lower", "unit": "rate_per_100"},
    "following_distance_rate": {"direction": "lower", "unit": "rate_per_100"},
    # Service reliability
    "fleet_execution":  {"direction": "lower",  "unit": "rate_per_100"},
}

# Retired by ADR-473, kept so a stale caller fails LOUDLY with a reason rather
# than a bare KeyError that reads like a typo.
RETIRED_METRICS: dict[str, str] = {
    "dcr": "replaced by 'dc_dpmo' — Amazon scores delivery completion as a "
           "defect rate where lower is better, not a percentage",
    "cdf": "replaced by 'cdf_dpmo' — customer feedback is a DPMO where lower "
           "is better, not a percentage",
    "dvic": "replaced by 'fleet_execution' — inspection QUALITY is a defect "
            "signal inside a fleet composite, not a completion percentage",
    "cc": "removed — contact compliance is an exemption mechanism inside "
          "delivery completion, not a scored metric with its own target",
    "dnr_dpmo": "removed — delivered-not-received is counted inside 'dsb_dpmo'",
}


def meets_target(key: str, value: float, target: float,
                 direction: str | None = None) -> bool:
    """True if `value` meets `target` for metric `key`.

    `direction` comes from the stored CompanyMetricTarget row. It is optional
    only so a caller holding just a key can still compare against the registry
    default; when a row exists, PASS ITS DIRECTION -- that is the row's purpose,
    and a company that has overridden the shape must not be judged by the
    default.

    Raises:
        ValueError — a retired metric key, naming what replaced it.
        KeyError — an unknown key. Deliberate: a new metric cannot be compared
        until someone states which direction is good.
    """
    if direction is None:
        if key in RETIRED_METRICS:
            raise ValueError(f"metric '{key}' is retired: {RETIRED_METRICS[key]}")
        direction = METRIC_SHAPES[key]["direction"]

    if direction not in ("higher", "lower"):
        # Never guess. A target whose direction is unreadable is exactly the
        # backwards comparison this ADR exists to stop.
        raise ValueError(f"metric '{key}' has an invalid direction {direction!r}")

    if direction == "lower":
        return value <= target
    return value >= target


# ---------------------------------------------------------------------------
# Resolved config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedConfig:
    """Resolved company config.  Required fields are always non-null.
    Optional fields (shift timing, driver_checkin_count) may be None.
    """

    # Operational (required)
    rating_window_hours:               int
    invite_expiry_days:                int

    # Training rules (required)
    graduation_assignments:            int
    debt_escalation_threshold:         int
    phase4_pass_score:                 float
    underperforming_trainer_threshold: int
    max_training_phase:                int

    # Dispatch weights (required)
    dispatch_weight_driver:            float
    dispatch_weight_trainer:           float
    dispatch_weight_walker:            float
    dispatch_mutual_bonus:             float
    dispatch_tridirectional_bonus:     float
    dispatch_consecutive_penalty:      float
    dispatch_weight_cap:               float

    # Walker rating (required)
    flag_threshold:                    float

    # Shift timing (optional — None if company doesn't use check-in tracking)
    shift_start:   time | None
    shift_end:     time | None
    checkin_open:  time | None
    checkin_close: time | None

    # Driver check-ins (optional)
    driver_checkin_count: int | None

    # Dispatch confirmation cutoff (optional — None means no cutoff enforced)
    dispatch_confirmation_cutoff: time | None

    # ── ADR-256 (defaulted, so they sit last: dataclass ordering) ─────────────
    # Deliberately NOT in _REQUIRED_FIELDS. A null in that tuple raises 503 for the
    # entire company, so listing these would take every existing tenant offline the
    # moment the migration adds a nullable column. The migration backfills them; the
    # defaults here cover the window between deploy and backfill, and any tenant
    # created by a path that predates the column.
    dispatch_weight_captain:     float = 0.50
    captain_truck_rotation_days: int = 5
    # Earlier confirmation deadline for driver + captain. None → fall back to
    # checkin_close, which is what those roles used before this column existed.
    early_confirmation_deadline: time | None = None

    # Scorecard tier targets (ADR-262) — all optional. None means the DSP has not
    # configured a target for that metric; callers must render the reported value
    # with no pass/fail judgement rather than treating None as a failure.

    def target_for(self, key: str) -> float | None:
        """Configured target for a metric key, or None if unset."""
        return getattr(self, METRIC_TARGET_FIELD[key], None)


# ---------------------------------------------------------------------------
# Discord guild config — separate from ResolvedConfig (optional integration)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscordGuildConfig:
    """Discord integration settings for a company.  All fields can be None if
    the company hasn't configured Discord yet — callers must handle None."""
    guild_id:            int | None
    drivers_channel_id:  int | None
    trainers_channel_id: int | None
    captains_channel_id: int | None
    general_channel_id:  int | None
    invite_channel_id:   int | None
    role_admin:          int | None
    role_manager:        int | None
    role_asheflow:       int | None
    role_bot:            int | None
    role_dispatch:       int | None
    role_driver:         int | None
    # Migration ff90779895f6 split trainer out of the captain role and added
    # `company_configs.discord_role_trainer`. It updated the DB, the ORM column,
    # and internal.py's reader — but NOT this dataclass or the two constructors
    # below, so `cfg.role_trainer` raised AttributeError on every guild-config
    # fetch. The bot treats that 500 as "Discord not configured" and skips
    # silently, which is why publishes returned 200 with no notification.
    role_trainer:        int | None
    role_captain:        int | None
    role_walker:         int | None

    @property
    def is_configured(self) -> bool:
        """True if at least a guild_id is set (minimum viable config)."""
        return self.guild_id is not None


def get_discord_config(db: Session, company_id: UUID) -> DiscordGuildConfig:
    """Return Discord integration settings for a company.

    Never raises — always returns a DiscordGuildConfig.
    Callers should check .is_configured before attempting Discord operations.
    """
    row = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if row is None:
        return DiscordGuildConfig(
            guild_id=None, drivers_channel_id=None, trainers_channel_id=None,
            captains_channel_id=None,
            general_channel_id=None, invite_channel_id=None,
            role_admin=None, role_manager=None, role_asheflow=None,
            role_bot=None, role_dispatch=None, role_driver=None,
            role_trainer=None, role_captain=None, role_walker=None,
        )
    return DiscordGuildConfig(
        guild_id            = row.discord_guild_id,
        drivers_channel_id  = row.discord_drivers_channel_id,
        trainers_channel_id = row.discord_trainers_channel_id,
        captains_channel_id = row.discord_captains_channel_id,
        general_channel_id  = row.discord_general_channel_id,
        invite_channel_id   = row.discord_invite_channel_id,
        role_admin          = row.discord_role_admin,
        role_manager        = row.discord_role_manager,
        role_asheflow       = row.discord_role_asheflow,
        role_bot            = row.discord_role_bot,
        role_dispatch       = row.discord_role_dispatch,
        role_driver         = row.discord_role_driver,
        role_trainer        = row.discord_role_trainer,
        role_captain        = row.discord_role_captain,
        role_walker         = row.discord_role_walker,
    )


def get_company_config(db: Session, company_id: UUID) -> ResolvedConfig:
    """Return the fully-resolved config for a company.

    Raises:
        HTTPException 500 — no CompanyConfig row exists (provisioning bug).
        HTTPException 503 — company has not completed initial setup.
        HTTPException 503 — one or more required fields are still null
                            (setup was marked complete with missing fields —
                            should not happen, but caught as a safety net).
    """
    row = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Company configuration record missing. Contact support.",
        )

    if not row.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company setup is not complete. Please finish the configuration before continuing.",
        )

    missing = [f for f in _REQUIRED_FIELDS if getattr(row, f) is None]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Company configuration is incomplete. Missing required fields: {', '.join(missing)}.",
        )

    return ResolvedConfig(
        rating_window_hours               = row.rating_window_hours,
        invite_expiry_days                = row.invite_expiry_days,
        graduation_assignments            = row.graduation_assignments,
        debt_escalation_threshold         = row.debt_escalation_threshold,
        phase4_pass_score                 = row.phase4_pass_score,
        underperforming_trainer_threshold = row.underperforming_trainer_threshold,
        max_training_phase                = row.max_training_phase,
        dispatch_weight_driver            = row.dispatch_weight_driver,
        dispatch_weight_trainer           = row.dispatch_weight_trainer,
        dispatch_weight_walker            = row.dispatch_weight_walker,
        dispatch_mutual_bonus             = row.dispatch_mutual_bonus,
        dispatch_tridirectional_bonus     = row.dispatch_tridirectional_bonus,
        dispatch_consecutive_penalty      = row.dispatch_consecutive_penalty,
        dispatch_weight_cap               = row.dispatch_weight_cap,
        flag_threshold                    = row.flag_threshold,
        shift_start                       = row.shift_start,
        shift_end                         = row.shift_end,
        checkin_open                      = row.checkin_open,
        checkin_close                     = row.checkin_close,
        driver_checkin_count              = row.driver_checkin_count,
        dispatch_confirmation_cutoff      = row.dispatch_confirmation_cutoff,
        # `or DEFAULT` rather than passing the column through: these are nullable and
        # excluded from _REQUIRED_FIELDS, so a null must resolve to the platform
        # default instead of propagating None into weight arithmetic.
        dispatch_weight_captain           = row.dispatch_weight_captain or PLATFORM_DEFAULTS["dispatch_weight_captain"],
        captain_truck_rotation_days       = row.captain_truck_rotation_days or PLATFORM_DEFAULTS["captain_truck_rotation_days"],
        early_confirmation_deadline       = row.early_confirmation_deadline,
    )

# ── Operating mode helpers (ADR-289) ─────────────────────────────────────────

def full_mode_company_ids(db) -> set:
    """company_ids whose tenant has an Amazon package feed (operating_mode='full').

    For cross-tenant background tasks, which iterate rows rather than companies and
    so cannot use the RequireMode request dependency. A task that reads package-path
    data must filter to these, or it burns work on tenants that structurally cannot
    produce that data — and, worse for `decay_troublesome_scores`, actively degrades
    stored intelligence that nothing is refreshing (ADR-293).
    """
    from app.models.company import CompanyConfig
    from app.services.constants import MODE_FULL

    rows = (
        db.query(CompanyConfig.company_id)
        .filter(CompanyConfig.operating_mode == MODE_FULL)
        .all()
    )
    return {r[0] for r in rows}


def is_full_mode(db, company_id) -> bool:
    """Does this ONE company have a package feed (operating_mode='full')?

    The request-path counterpart to `full_mode_company_ids`, which exists for
    cross-tenant background tasks. A request already knows its company, so
    loading every full-mode id to test one of them would be wasteful.
    """
    from app.models.company import CompanyConfig
    from app.services.constants import MODE_FULL

    cfg = (
        db.query(CompanyConfig.operating_mode)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    return bool(cfg and cfg[0] == MODE_FULL)
