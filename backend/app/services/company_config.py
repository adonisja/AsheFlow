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
    "dispatch_weight_driver":           0.70,
    "dispatch_weight_trainer":          0.50,
    "dispatch_weight_walker":           0.30,
    "dispatch_mutual_bonus":            0.10,
    "dispatch_tridirectional_bonus":    0.20,
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
    general_channel_id:  int | None
    invite_channel_id:   int | None
    role_admin:          int | None
    role_manager:        int | None
    role_asheflow:       int | None
    role_bot:            int | None
    role_dispatch:       int | None
    role_driver:         int | None
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
            general_channel_id=None, invite_channel_id=None,
            role_admin=None, role_manager=None, role_asheflow=None,
            role_bot=None, role_dispatch=None, role_driver=None,
            role_captain=None, role_walker=None,
        )
    return DiscordGuildConfig(
        guild_id            = row.discord_guild_id,
        drivers_channel_id  = row.discord_drivers_channel_id,
        trainers_channel_id = row.discord_trainers_channel_id,
        general_channel_id  = row.discord_general_channel_id,
        invite_channel_id   = row.discord_invite_channel_id,
        role_admin          = row.discord_role_admin,
        role_manager        = row.discord_role_manager,
        role_asheflow       = row.discord_role_asheflow,
        role_bot            = row.discord_role_bot,
        role_dispatch       = row.discord_role_dispatch,
        role_driver         = row.discord_role_driver,
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
    )
