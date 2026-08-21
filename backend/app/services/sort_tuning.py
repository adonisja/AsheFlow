"""Resolve route-sort tuning constants from CompanyConfig, or fall back (ADR-273).

WHY THIS EXISTS
The seed weights, traversal guards, and F5 consolidation knobs were module
constants in `route_sort.py`. ADR-273 adds telemetry whose whole purpose is to
tell an operator *which of them to move*; a constant that needs a deploy to
change cannot be tuned from a dashboard, so the values become per-tenant config.

THE FALLBACK RULE
Every field is nullable and **null means "use the code default"**. They are
deliberately NOT in `company_config._REQUIRED_FIELDS`: a null in that tuple
raises 503 for the entire tenant, so listing them would take every existing
company offline the moment the migration adds the columns. A tenant that has
never opened the tuning page must keep sorting exactly as before.

WHY A DATACLASS AND NOT A DICT
The resolved bundle is passed into the sort and then written verbatim onto
`RouteSortRun`. A dataclass keeps "what the algorithm ran with" and "what we
recorded it ran with" the same object, so the two cannot drift — which is the
failure this telemetry exists to prevent.

Public module: reads config, holds no routing algorithm.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

# Code defaults — the values route_sort.py used before they were configurable.
# Kept here (not imported from route_sort) so this module stays public and
# importable without pulling in the proprietary sort service.
DEFAULT_W_DENSE = 1.0
DEFAULT_W_TIME = 1.5
DEFAULT_W_DIFF = 1.3
DEFAULT_W_DOORMAN = 0.5
DEFAULT_WALK_BUDGET_M = 900.0
DEFAULT_SPAN_CAP_M = 700.0
DEFAULT_MAX_CONSECUTIVE_NO_FIT = 2
DEFAULT_F5_LOAD_FLOOR_HS = 6
DEFAULT_F5_MAX_HOPS = 2
DEFAULT_F5_WALK_RADIUS_KM = 0.8

# Route assembly modes (ADR-272).
MODE_BLOCK_COMPLETION = "block_completion"
MODE_GROUP_FIRST = "group_first"
VALID_ASSEMBLY_MODES = frozenset({MODE_BLOCK_COMPLETION, MODE_GROUP_FIRST})
DEFAULT_ASSEMBLY_MODE = MODE_BLOCK_COMPLETION

# Bumped whenever a change alters route composition. Written to
# RouteSortRun.algorithm_version — the column that makes "did the change help?"
# a GROUP BY rather than a recollection. The assembly mode is part of the
# identity because two tenants on different modes must not pool into one series.
ALGORITHM_BASE_VERSION = "v1"


@dataclass(frozen=True)
class SortTuning:
    """Resolved tuning for one sort run. Immutable once built."""

    w_dense: float = DEFAULT_W_DENSE
    w_time: float = DEFAULT_W_TIME
    w_diff: float = DEFAULT_W_DIFF
    w_doorman: float = DEFAULT_W_DOORMAN

    walk_budget_m: float = DEFAULT_WALK_BUDGET_M
    span_cap_m: float = DEFAULT_SPAN_CAP_M
    max_consecutive_no_fit: int = DEFAULT_MAX_CONSECUTIVE_NO_FIT

    f5_load_floor_hs: int = DEFAULT_F5_LOAD_FLOOR_HS
    f5_max_hops: int = DEFAULT_F5_MAX_HOPS
    f5_walk_radius_km: float = DEFAULT_F5_WALK_RADIUS_KM

    assembly_mode: str = DEFAULT_ASSEMBLY_MODE

    @property
    def algorithm_version(self) -> str:
        """Identity of the code+mode combination that produced a sort.

        e.g. "block_completion_v1" / "group_first_v1". Weight changes do NOT
        bump this — they are recorded as their own columns on RouteSortRun, so a
        weight sweep stays inside one comparable population, while an assembly
        change splits it.
        """
        return f"{self.assembly_mode}_{ALGORITHM_BASE_VERSION}"

    def as_telemetry(self) -> dict:
        """The subset persisted on RouteSortRun (weights + guards)."""
        d = asdict(self)
        return {
            "w_dense": d["w_dense"],
            "w_time": d["w_time"],
            "w_diff": d["w_diff"],
            "w_doorman": d["w_doorman"],
            "walk_budget_m": d["walk_budget_m"],
            "span_cap_m": d["span_cap_m"],
        }


def _pick(value, default):
    """Config value when set, else the code default. Null means 'use default'."""
    return default if value is None else value


def resolve_sort_tuning(db: Session, company_id: UUID) -> SortTuning:
    """Build the SortTuning for a company. Never raises; falls back on defaults.

    A missing CompanyConfig row is not an error here — the sort must still run
    on defaults rather than 500 on a lookup for an optional tuning table.
    """
    from app.models.company import CompanyConfig

    cfg = (
        db.query(CompanyConfig)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    if cfg is None:
        return SortTuning()

    mode = cfg.route_assembly_mode
    if mode not in VALID_ASSEMBLY_MODES:
        # An unrecognised value must never silently select an experimental
        # branch. Fail closed to the shipped default.
        mode = DEFAULT_ASSEMBLY_MODE

    return SortTuning(
        w_dense=_pick(cfg.sort_w_dense, DEFAULT_W_DENSE),
        w_time=_pick(cfg.sort_w_time, DEFAULT_W_TIME),
        w_diff=_pick(cfg.sort_w_diff, DEFAULT_W_DIFF),
        w_doorman=_pick(cfg.sort_w_doorman, DEFAULT_W_DOORMAN),
        walk_budget_m=_pick(cfg.sort_walk_budget_m, DEFAULT_WALK_BUDGET_M),
        span_cap_m=_pick(cfg.sort_span_cap_m, DEFAULT_SPAN_CAP_M),
        max_consecutive_no_fit=_pick(
            cfg.sort_max_consecutive_no_fit, DEFAULT_MAX_CONSECUTIVE_NO_FIT
        ),
        f5_load_floor_hs=_pick(cfg.sort_f5_load_floor_hs, DEFAULT_F5_LOAD_FLOOR_HS),
        f5_max_hops=_pick(cfg.sort_f5_max_hops, DEFAULT_F5_MAX_HOPS),
        f5_walk_radius_km=_pick(cfg.sort_f5_walk_radius_km, DEFAULT_F5_WALK_RADIUS_KM),
        assembly_mode=mode,
    )
