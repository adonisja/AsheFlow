"""
company_config.py — resolved company configuration helper.

Call get_company_config(db, company_id) to get a ResolvedConfig object whose
fields are always non-null: DB value when set, hardcoded default otherwise.
Services import ResolvedConfig for type hints and get_company_config for lookup.

This is the single place where null-fallback logic lives. Callers never need to
write `config.field or DEFAULT` — they just use the returned object directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import CompanyConfig


# ---------------------------------------------------------------------------
# Defaults — match the values that were hardcoded in constants.py / settings
# ---------------------------------------------------------------------------

_D_SHIFT_START    = time(7, 0)
_D_SHIFT_END      = time(18, 0)
_D_CHECKIN_OPEN   = time(6, 30)
_D_CHECKIN_CLOSE  = time(7, 45)

_D_RATING_WINDOW_HOURS            = 6
_D_INVITE_EXPIRY_DAYS             = 7

_D_MIN_TRAINERS_PER_TRUCK         = 2
_D_MIN_WALKERS_PER_TRUCK          = 3

_D_GRADUATION_ASSIGNMENTS         = 5
_D_DEBT_ESCALATION_THRESHOLD      = 3
_D_PHASE4_PASS_SCORE              = 90.0
_D_UNDERPERFORMING_TRAINER_THRESHOLD = 3
_D_MAX_TRAINING_PHASE             = 4

_D_DISPATCH_WEIGHT_DRIVER         = 0.70
_D_DISPATCH_WEIGHT_TRAINER        = 0.50
_D_DISPATCH_WEIGHT_WALKER         = 0.30
_D_DISPATCH_MUTUAL_BONUS          = 0.10
_D_DISPATCH_TRIDIRECTIONAL_BONUS  = 0.20
_D_DISPATCH_CONSECUTIVE_PENALTY   = 0.05
_D_DISPATCH_WEIGHT_CAP            = 0.85

_D_FLAG_THRESHOLD                 = 1.0
_D_DRIVER_CHECKIN_COUNT           = 4


# ---------------------------------------------------------------------------
# Resolved config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedConfig:
    """All config values with nulls replaced by platform defaults."""

    # Shift timing
    shift_start:   time
    shift_end:     time
    checkin_open:  time
    checkin_close: time

    # Operational
    rating_window_hours:              int
    invite_expiry_days:               int

    # Crew requirements
    min_trainers_per_truck:           int
    min_walkers_per_truck:            int

    # Training rules
    graduation_assignments:           int
    debt_escalation_threshold:        int
    phase4_pass_score:                float
    underperforming_trainer_threshold: int
    max_training_phase:               int

    # Dispatch weights
    dispatch_weight_driver:           float
    dispatch_weight_trainer:          float
    dispatch_weight_walker:           float
    dispatch_mutual_bonus:            float
    dispatch_tridirectional_bonus:    float
    dispatch_consecutive_penalty:     float
    dispatch_weight_cap:              float

    # Walker rating
    flag_threshold:                   float

    # Driver check-ins
    driver_checkin_count:             int


def get_company_config(db: Session, company_id: UUID) -> ResolvedConfig:
    """Fetch CompanyConfig for company_id and return a fully-resolved object.

    Every field is guaranteed non-null: DB value when explicitly set,
    platform default otherwise. Raises ValueError if no config row exists
    (every active company must have one — created at provisioning time).
    """
    row = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if row is None:
        raise ValueError(
            f"No CompanyConfig row found for company_id={company_id}. "
            "Every active company must have a config row created at provisioning."
        )

    return ResolvedConfig(
        shift_start   = row.shift_start   or _D_SHIFT_START,
        shift_end     = row.shift_end     or _D_SHIFT_END,
        checkin_open  = row.checkin_open  or _D_CHECKIN_OPEN,
        checkin_close = row.checkin_close or _D_CHECKIN_CLOSE,

        rating_window_hours              = row.rating_window_hours              or _D_RATING_WINDOW_HOURS,
        invite_expiry_days               = row.invite_expiry_days               or _D_INVITE_EXPIRY_DAYS,

        min_trainers_per_truck           = row.min_trainers_per_truck           or _D_MIN_TRAINERS_PER_TRUCK,
        min_walkers_per_truck            = row.min_walkers_per_truck            or _D_MIN_WALKERS_PER_TRUCK,

        graduation_assignments           = row.graduation_assignments           or _D_GRADUATION_ASSIGNMENTS,
        debt_escalation_threshold        = row.debt_escalation_threshold        or _D_DEBT_ESCALATION_THRESHOLD,
        phase4_pass_score                = row.phase4_pass_score                or _D_PHASE4_PASS_SCORE,
        underperforming_trainer_threshold = row.underperforming_trainer_threshold or _D_UNDERPERFORMING_TRAINER_THRESHOLD,
        max_training_phase               = row.max_training_phase               or _D_MAX_TRAINING_PHASE,

        dispatch_weight_driver           = row.dispatch_weight_driver           or _D_DISPATCH_WEIGHT_DRIVER,
        dispatch_weight_trainer          = row.dispatch_weight_trainer          or _D_DISPATCH_WEIGHT_TRAINER,
        dispatch_weight_walker           = row.dispatch_weight_walker           or _D_DISPATCH_WEIGHT_WALKER,
        dispatch_mutual_bonus            = row.dispatch_mutual_bonus            or _D_DISPATCH_MUTUAL_BONUS,
        dispatch_tridirectional_bonus    = row.dispatch_tridirectional_bonus    or _D_DISPATCH_TRIDIRECTIONAL_BONUS,
        dispatch_consecutive_penalty     = row.dispatch_consecutive_penalty     or _D_DISPATCH_CONSECUTIVE_PENALTY,
        dispatch_weight_cap              = row.dispatch_weight_cap              or _D_DISPATCH_WEIGHT_CAP,

        flag_threshold                   = row.flag_threshold                   or _D_FLAG_THRESHOLD,
        driver_checkin_count             = row.driver_checkin_count             or _D_DRIVER_CHECKIN_COUNT,
    )
