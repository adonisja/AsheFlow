"""Preference strength as a target probability (ADR-356).

Replaces the multiplier-plus-flat-bonus model, which compressed every signal
into 17-49%: role boosts multiplied the running weight while the mutual and
tridirectional bonuses added a flat 0.10/0.20, so the bonuses meant to mark the
STRONGEST signals were the smallest terms in the formula. A full mutual trio
measured 37.9% against an intended 70%.

A flat bonus is also tuned to one fleet size. The same constants give 85% at
three trucks and 51% at twelve, so a number chosen on a six-truck day silently
means something else on every other day.

Here each tier is a probability, and the weight needed to achieve it is derived
from the truck count at runtime.
"""
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Roles whose preference carries the most weight, in descending strength.
# Mirrors ADR-355 D2: the tier is chosen by WHO EXPRESSED the preference.
_STRONG_ROLES = ("driver", "captain")

# ADR-356 D2. Ordered weakest to strongest; the STRONGEST match wins (D3).
DEFAULT_TARGETS: dict[str, float] = {
    "oneway_weak":    0.22,   # a walker favours you
    "oneway_trainer": 0.25,   # a trainer favours you
    "oneway_captain": 0.28,
    "oneway_driver":  0.33,
    # Mutual pairs are ranked by WHICH TWO ROLES bonded, not merely by whether a
    # crew lead is involved. The driver and captain jointly control and organise
    # the truck, so their bond has the largest effect on the day's outcome; a
    # driver-trainer bond means less friction for the trainer, who can then focus
    # on their paired trainee; anything else is an ordinary good pairing.
    "mutual_weak":          0.45,   # neither half is a driver or captain
    "mutual_lead_crew":     0.55,   # driver or captain paired with anyone else
    "mutual_driver_trainer": 0.60,  # driver <-> trainer
    "mutual_driver_captain": 0.65,  # driver <-> captain -- the strongest pair
    "tridirectional": 0.80,   # six favours among driver + captain + walker
    "trio_plus":      0.88,   # trio, and a trainer favours the candidate too
}

# Highest first — resolution returns on the first match (D3).
_TIER_ORDER = (
    "trio_plus",
    "tridirectional",
    "mutual_driver_captain",
    "mutual_driver_trainer",
    "mutual_lead_crew",
    "mutual_weak",
    "oneway_driver",
    "oneway_captain",
    "oneway_trainer",
    "oneway_weak",
)


def weight_for_target(target: float, truck_count: int) -> float:
    """Weight that yields `target` probability against `truck_count - 1` unweighted trucks.

    Inverts P = w / (w + (N-1)).

    A target of 1.0 would divide by zero. That is not a tuning value but a
    CONSTRAINT expressed as a probability — "always this truck" — and belongs to
    crew pinning, so it raises rather than being silently clamped to something
    that merely looks certain.
    """
    if not 0.0 <= target < 1.0:
        raise ValueError(
            f"preference target must be in [0, 1), got {target!r}. "
            "1.0 means 'always', which is a pin, not a preference."
        )
    if truck_count < 2:
        # One truck: every candidate lands there regardless. No pull to express.
        return 1.0

    # A preference must never make a truck LESS likely than chance, and the tier
    # ORDER must survive every fleet size.
    #
    # The targets are calibrated for a mid-sized fleet (17% baseline at six
    # trucks). On a SMALL fleet the baseline is higher than the lower tiers, so a
    # naive conversion inverts them: at two trucks the 33% "a driver favours you"
    # target yields weight 0.49 against an unweighted 1.0 — a penalty for being
    # picked.
    #
    # Two fixes were tried and rejected. Flooring at the baseline removes the
    # inversion but flattens every weak tier to exactly neutral, erasing the
    # ordering. Rescaling only the sub-baseline tiers makes them collide with the
    # untouched ones — at N=2 it put oneway_weak (61%) above mutual_strong (55%).
    #
    # Rescale the WHOLE ladder uniformly instead: map [0,1) onto [baseline,1) so
    # every tier keeps its rank and its spacing, and none can fall below chance.
    # On a fleet where baseline is already below the weakest tier (six trucks and
    # up) this is close to the identity, so the stated targets hold where they
    # were calibrated.
    # Rescale ONLY when the fleet is small enough that a tier would otherwise
    # fall below chance. On a fleet where the baseline already sits under the
    # weakest tier — six trucks and up, where these targets were calibrated — the
    # stated probabilities are used verbatim, so "70%" means 70%.
    baseline = 1.0 / truck_count
    weakest = min(DEFAULT_TARGETS.values())
    if baseline < weakest:
        effective = target
    else:
        effective = baseline + (1.0 - baseline) * target

    if effective >= 1.0:
        return 1.0
    return effective * (truck_count - 1) / (1.0 - effective)


def resolve_tier(
    *,
    expressed_by_roles: Iterable[str],
    mutual_roles: Iterable[str],
    candidate_role: Optional[str] = None,
    has_trio: bool = False,
    trainer_also_favs: bool = False,
) -> Optional[str]:
    """Name the strongest tier this candidate has earned on one truck.

    Args:
        expressed_by_roles: roles of everyone whose one-way favourite points at
            this pairing — the role of the EXPRESSOR, per ADR-355 D2.
        mutual_roles: roles of the PLACED members in any reciprocated pair.
        candidate_role: the candidate's own role — the other half of every pair.
            Without it driver<->captain and driver<->walker are indistinguishable,
            since both arrive as mutual_roles=["driver"].
        has_trio: all six favourites exist among driver + captain + candidate.
        trainer_also_favs: a trainer on this truck also favours the candidate.

    Returns:
        A key of DEFAULT_TARGETS, or None when there is no signal at all.
    """
    expressed = {r for r in expressed_by_roles if r}
    mutual = {r for r in mutual_roles if r}

    if has_trio and trainer_also_favs:
        return "trio_plus"
    if has_trio:
        return "tridirectional"
    if mutual:
        # Both halves of the pair, so the specific bond can be ranked.
        pairs = {frozenset((candidate_role, r)) for r in mutual if candidate_role}
        if frozenset(("driver", "captain")) in pairs:
            return "mutual_driver_captain"
        if frozenset(("driver", "trainer")) in pairs:
            return "mutual_driver_trainer"
        if mutual & set(_STRONG_ROLES) or (candidate_role in _STRONG_ROLES):
            return "mutual_lead_crew"
        return "mutual_weak"
    if "driver" in expressed:
        return "oneway_driver"
    if "captain" in expressed:
        return "oneway_captain"
    if "trainer" in expressed:
        return "oneway_trainer"
    if expressed:
        return "oneway_weak"
    return None


def target_for(tier: Optional[str], cfg=None) -> Optional[float]:
    """Configured target for a tier, falling back to the platform default.

    Reads `dispatch_target_<tier>` so a tenant can tune one tier without
    inheriting the rest.
    """
    if tier is None:
        return None
    value = getattr(cfg, f"dispatch_target_{tier}", None) if cfg else None
    if value is None:
        return DEFAULT_TARGETS[tier]
    return value
