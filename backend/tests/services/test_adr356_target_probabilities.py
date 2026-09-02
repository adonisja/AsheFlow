"""ADR-356 — preference strength is a target probability, not a multiplier.

The old model multiplied the running weight by a role boost and then added a
flat 0.10/0.20 bonus. Measured on staging that compressed every signal into
17-49%: a full mutual trio, the strongest signal the system can express, reached
37.9% against an intended 70%. The bonuses meant to mark the STRONGEST signals
were the smallest terms in the formula.

A flat bonus is also tuned to one fleet size — the same constants gave 85% at
three trucks and 51% at twelve.

Two invariants below were design flaws found while implementing this, not
hypotheticals:

  * At two trucks the baseline is 50%, so converting a 33% target verbatim gave
    weight 0.49 — a driver favouring you made their truck LESS likely than
    chance.
  * Flooring at the baseline fixed that but flattened every weak tier to exactly
    neutral. Rescaling only the sub-baseline tiers then made them collide with
    the untouched ones: at N=2, oneway_weak (61%) outranked mutual_strong (55%).
"""
import pytest

from app.services.preference_tiers import (
    DEFAULT_TARGETS,
    resolve_tier,
    target_for,
    weight_for_target,
)

FLEETS = (2, 3, 4, 5, 6, 8, 12, 20)


def _p(weight: float, n: int) -> float:
    return weight / (weight + (n - 1))


@pytest.mark.parametrize("n", FLEETS)
def test_a_preference_never_makes_a_truck_less_likely_than_chance(n):
    """The inversion bug: a favourite must never be a penalty."""
    baseline = 1.0 / n
    for tier, target in DEFAULT_TARGETS.items():
        p = _p(weight_for_target(target, n), n)
        assert p >= baseline - 1e-9, (
            f"{tier} at {n} trucks gives {p:.1%}, below the {baseline:.1%} "
            "baseline — being favoured would hurt"
        )


@pytest.mark.parametrize("n", FLEETS)
def test_the_ladder_stays_ordered_at_every_fleet_size(n):
    """The collision bug: rescaling must not reorder the tiers."""
    order = list(DEFAULT_TARGETS)
    probs = [_p(weight_for_target(DEFAULT_TARGETS[t], n), n) for t in order]
    for i in range(1, len(probs)):
        assert probs[i] >= probs[i - 1] - 1e-9, (
            f"at {n} trucks {order[i]} ({probs[i]:.1%}) ranks below "
            f"{order[i-1]} ({probs[i-1]:.1%})"
        )


@pytest.mark.parametrize("n", (5, 6, 8, 12, 20))
def test_the_stated_targets_hold_on_a_real_fleet(n):
    """The whole point: 70% means 70% regardless of truck count.

    Only from five trucks up — below that the baseline exceeds the weakest tier
    and the ladder is rescaled to stay ordered, which necessarily moves the top.
    """
    assert _p(weight_for_target(0.70, n), n) == pytest.approx(0.70, abs=1e-6)
    assert _p(weight_for_target(0.80, n), n) == pytest.approx(0.80, abs=1e-6)


def test_a_target_of_one_is_rejected_not_clamped():
    """1.0 means 'always', which is a pin. Clamping would divide by zero or lie."""
    with pytest.raises(ValueError):
        weight_for_target(1.0, 6)
    with pytest.raises(ValueError):
        weight_for_target(1.5, 6)


def test_the_strongest_tier_wins_and_tiers_do_not_stack():
    """D3 — if a trio means 70%, extra one-way favs must not push it higher."""
    trio = resolve_tier(
        expressed_by_roles=["driver", "captain", "walker"],
        mutual_roles=["driver", "captain"],
        has_trio=True,
    )
    assert trio == "tridirectional"

    with_trainer = resolve_tier(
        expressed_by_roles=["driver", "captain", "walker", "trainer"],
        mutual_roles=["driver"],
        has_trio=True,
        trainer_also_favs=True,
    )
    assert with_trainer == "trio_plus"


def test_the_expressors_role_picks_the_tier():
    """ADR-355 D2 carried forward — a driver's pick outranks a walker's."""
    assert resolve_tier(expressed_by_roles=["driver"], mutual_roles=[]) == "oneway_driver"
    assert resolve_tier(expressed_by_roles=["captain"], mutual_roles=[]) == "oneway_captain"
    assert resolve_tier(expressed_by_roles=["walker"], mutual_roles=[]) == "oneway_weak"
    assert resolve_tier(expressed_by_roles=["trainer"], mutual_roles=[]) == "oneway_weak"
    assert resolve_tier(expressed_by_roles=[], mutual_roles=[]) is None


def test_a_mutual_pair_outranks_any_one_way():
    assert resolve_tier(expressed_by_roles=["driver"], mutual_roles=["driver"]) == "mutual_strong"
    assert resolve_tier(expressed_by_roles=["walker"], mutual_roles=["walker"]) == "mutual_weak"


def test_config_overrides_the_platform_default():
    class Cfg:
        dispatch_target_tridirectional = 0.55

    assert target_for("tridirectional", Cfg()) == 0.55
    assert target_for("tridirectional", None) == DEFAULT_TARGETS["tridirectional"]
    assert target_for(None, None) is None
