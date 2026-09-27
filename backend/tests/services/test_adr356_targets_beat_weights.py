"""Targets hold their probability across fleet sizes; flat bonuses do not (ADR-356).

ADR-356 replaced role multipliers and flat bonuses with per-tier target
probabilities. Its supporting measurement lived only in the ADR's prose. These
tests assert the property the decision rests on, so it is checkable rather than
quoted -- and so a future attempt to reinstate weights has to argue with a
failing test rather than an old paragraph.

Pure arithmetic: no database, no dispatch run, no staging writes.
"""
import pytest

from app.services.preference_tiers import (
    DEFAULT_TARGETS,
    _TIER_ORDER,
    weight_for_target,
)

# P = w / (w + (N-1)) -- the probability a weighted truck wins against N-1
# unweighted ones. This is the model both schemes are measured against; only
# the way `w` is produced differs.
def probability(weight: float, truck_count: int) -> float:
    return weight / (weight + (truck_count - 1))


# The pre-ADR-356 scheme, reconstructed from the ADR's Context section:
# role boosts MULTIPLY the running weight, bonuses ADD a flat amount.
def legacy_weight(*, role_boost: float, flat_bonus: float) -> float:
    w = 1.0
    w += w * role_boost
    w += flat_bonus
    return w


FLEET_SIZES = (3, 4, 6, 8, 10, 12)

# Where the stated targets are used verbatim. Below this the baseline (1/N)
# exceeds the weakest tier, so weight_for_target rescales the whole ladder to
# stop a weak favour becoming a PENALTY -- see its comment for the two rejected
# alternatives. The boundary is the fleet size at which 1/N drops under the
# weakest target (0.22), i.e. N >= 5.
VERBATIM_FLEET_SIZES = tuple(n for n in FLEET_SIZES if 1.0 / n < min(DEFAULT_TARGETS.values()))


# ── the claim: a target holds across fleet sizes ────────────────────────────

@pytest.mark.parametrize("tier", sorted(DEFAULT_TARGETS))
def test_a_target_holds_its_probability_at_every_calibrated_fleet_size(tier):
    """The whole reason for ADR-356. 70% must mean 70% at 6 trucks and at 12.

    Scoped to fleets at or above the calibration point. The first version of
    this test asserted EVERY size and failed at N=3 -- correctly, because the
    code deliberately rescales there. Asserting the naive claim would have made
    the test wrong and the code look broken.
    """
    target = DEFAULT_TARGETS[tier]
    for n in VERBATIM_FLEET_SIZES:
        got = probability(weight_for_target(target, n), n)
        assert got == pytest.approx(target, abs=1e-9), (
            f"{tier}: target {target} drifted to {got:.4f} at {n} trucks"
        )


@pytest.mark.parametrize("tier", sorted(DEFAULT_TARGETS))
def test_a_small_fleet_rescales_upward_never_below_the_target(tier):
    """On a small fleet the ladder is lifted, not dropped.

    At N=3 the baseline is 33% -- above the weakest tier's 22% -- so using the
    target verbatim would place a favoured walker BELOW chance. The rescale
    lifts every tier and keeps the ordering.
    """
    target = DEFAULT_TARGETS[tier]
    for n in (2, 3, 4):
        got = probability(weight_for_target(target, n), n)
        assert got >= target - 1e-9, (
            f"{tier}: small fleet dropped {target} to {got:.4f} at {n} trucks"
        )


def test_a_flat_bonus_does_not_hold_across_fleet_sizes():
    """The defect ADR-356 measured: the same numbers mean different things.

    Reproduces the ADR's table -- a full trio reaching 85% at 3 trucks and 51%
    at 12 -- from the legacy formula rather than quoting it.
    """
    w = legacy_weight(role_boost=0.70, flat_bonus=0.20)
    at_3 = probability(w, 3)
    at_12 = probability(w, 12)
    assert at_3 > 0.40, f"expected a high share at 3 trucks, got {at_3:.3f}"
    assert at_12 < 0.20, f"expected collapse at 12 trucks, got {at_12:.3f}"
    spread = at_3 - at_12
    assert spread > 0.25, (
        f"a flat bonus should swing wildly with fleet size; spread was {spread:.3f}"
    )


def test_the_legacy_scheme_cannot_reach_the_intended_strength():
    """ADR-356: the strongest signal reached 37.9% against an intended ~70%."""
    w = legacy_weight(role_boost=0.70, flat_bonus=0.20)
    assert probability(w, 6) < 0.40
    # The target scheme reaches it by construction.
    assert probability(weight_for_target(0.70, 6), 6) == pytest.approx(0.70)


# ── ordering and safety, which a replacement must also preserve ─────────────

def test_the_tier_ladder_never_inverts_at_any_fleet_size():
    """A stronger signal must never place a crew together LESS often."""
    ordered = [t for t in _TIER_ORDER if t in DEFAULT_TARGETS]
    for n in FLEET_SIZES:
        probs = [probability(weight_for_target(DEFAULT_TARGETS[t], n), n)
                 for t in ordered]
        # _TIER_ORDER is strongest-first, so probabilities must descend.
        assert probs == sorted(probs, reverse=True), (
            f"ladder inverted at {n} trucks: "
            + ", ".join(f"{t}={p:.3f}" for t, p in zip(ordered, probs))
        )


def test_a_preference_never_makes_a_truck_worse_than_chance():
    """A weak favour must still beat the 1/N baseline, not fall below it."""
    for n in FLEET_SIZES:
        baseline = 1.0 / n
        weakest = min(DEFAULT_TARGETS.values())
        got = probability(weight_for_target(weakest, n), n)
        assert got >= baseline - 1e-9, (
            f"weakest tier {got:.3f} is below chance {baseline:.3f} at {n} trucks"
        )


def test_a_target_of_one_is_rejected_as_a_pin():
    """ADR-356 D5 / Dim 5: 1.0 divides by zero and means 'always', not 'prefer'."""
    with pytest.raises(ValueError, match="pin, not a preference"):
        weight_for_target(1.0, 6)


def test_a_single_truck_needs_no_pull():
    assert weight_for_target(0.70, 1) == 1.0
