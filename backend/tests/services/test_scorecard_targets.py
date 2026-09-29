"""Scorecard target direction (ADR-262, re-pointed by ADR-473).

The bug this file exists to prevent: a generic `value >= target` helper silently
inverts every DPMO metric. It does not raise and does not fail typing -- it just
reports an excellent DPMO of 400 as failing a 950 ceiling.

A test that only exercises higher-is-better metrics passes identically against
the broken version, so every case below asserts BOTH sides of the comparison.

ADR-473 REWROTE WHAT THIS POINTS AT, not what it is for. The old shape was two
hand-maintained maps (METRIC_DIRECTION, METRIC_TARGET_FIELD) that had to agree
with each other and with ten columns. Five of those columns had the wrong
direction or unit against Amazon's own guides, so the maps were mutually
consistent AND wrong -- which is precisely what "map integrity" tests cannot
catch. Direction now travels with the stored target.
"""
import pytest

from app.models.metric_target import VALID_DIRECTIONS, VALID_UNITS
from app.services.company_config import (
    METRIC_SHAPES,
    RETIRED_METRICS,
    meets_target,
)


# ---------------------------------------------------------------------------
# Higher-is-better: value must be AT OR ABOVE target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["pod", "fico"])
def test_higher_is_better_passes_above_and_fails_below(key):
    assert meets_target(key, 100.0, 99.0) is True   # above target passes
    assert meets_target(key, 99.0, 99.0) is True    # exactly at target passes
    assert meets_target(key, 98.9, 99.0) is False   # below target fails


# ---------------------------------------------------------------------------
# Lower-is-better: value must be AT OR BELOW target.
# These are the cases a generic `>=` gets backwards.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "dsb_dpmo", "cdf_dpmo", "dc_dpmo",
    "speeding_rate", "signsignal_rate",
    "seatbelt_rate", "distractions_rate", "following_distance_rate",
    "fleet_execution",
])
def test_lower_is_better_passes_below_and_fails_above(key):
    assert meets_target(key, 400.0, 950.0) is True    # well under target passes
    assert meets_target(key, 950.0, 950.0) is True    # exactly at target passes
    assert meets_target(key, 9000.0, 950.0) is False  # over target fails


def test_cdf_is_not_evaluated_as_higher_is_better():
    """The specific inversion ADR-473 found, stated as its own case.

    CDF was modelled as a percentage where higher passes. It is a DPMO where
    LOWER passes, and the request schema capped it at 100 -- so a real target
    could not even be stored. Both halves are asserted here because the cap made
    the inversion invisible: nobody could enter a value large enough to notice.
    """
    assert meets_target("cdf_dpmo", 900.0, 980.0) is True
    assert meets_target("cdf_dpmo", 1100.0, 980.0) is False


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

def test_unknown_metric_key_raises():
    """A new metric cannot be compared until someone states its direction."""
    with pytest.raises(KeyError):
        meets_target("brand_new_metric", 1.0, 1.0)


def test_a_retired_key_raises_with_a_reason():
    """Distinct from the unknown case on purpose. A bare KeyError on a key that
    used to work reads as a typo, and the next person re-adds the column."""
    for key in RETIRED_METRICS:
        with pytest.raises(ValueError) as exc:
            meets_target(key, 1.0, 1.0)
        assert key in str(exc.value)


def test_every_shape_is_valid():
    for key, shape in METRIC_SHAPES.items():
        assert shape["direction"] in VALID_DIRECTIONS, key
        assert shape["unit"] in VALID_UNITS, key


def test_a_stored_direction_overrides_the_registry():
    """The point of storing it. A company whose metric has a different shape
    must be judged by its own row, not by our default -- and this is the test
    that would have caught the original defect, because it does not assume the
    registry is right."""
    assert meets_target("pod", 5.0, 10.0, direction="lower") is True
    assert meets_target("dsb_dpmo", 15.0, 10.0, direction="higher") is True


def test_no_retired_key_is_still_live():
    assert not (set(RETIRED_METRICS) & set(METRIC_SHAPES))
