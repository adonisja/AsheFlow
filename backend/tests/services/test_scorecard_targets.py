"""ADR-262 — scorecard target direction.

The bug this file exists to prevent: a generic `value >= target` helper silently
inverts every DPMO metric. It does not raise and does not fail typing — it just
reports an excellent DNR DPMO of 400 as failing a <=950 target.

A test that only exercises higher-is-better metrics passes identically against
the broken version, so every case below asserts BOTH sides of the comparison.
"""
import pytest

from app.services.company_config import (
    METRIC_DIRECTION,
    METRIC_TARGET_FIELD,
    meets_target,
)


# ---------------------------------------------------------------------------
# Higher-is-better: value must be AT OR ABOVE target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["dcr", "pod", "cc", "cdf", "fico", "dvic"])
def test_higher_is_better_passes_above_and_fails_below(key):
    assert meets_target(key, 100.0, 99.0) is True   # above target passes
    assert meets_target(key, 99.0, 99.0) is True    # exactly at target passes
    assert meets_target(key, 98.9, 99.0) is False   # below target fails


# ---------------------------------------------------------------------------
# Lower-is-better: value must be AT OR BELOW target.
# These are the cases a generic `>=` gets backwards.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key", ["dnr_dpmo", "dsb_dpmo", "speeding_rate", "signsignal_rate"]
)
def test_lower_is_better_passes_below_and_fails_above(key):
    assert meets_target(key, 400.0, 950.0) is True    # well under target passes
    assert meets_target(key, 950.0, 950.0) is True    # exactly at target passes
    assert meets_target(key, 9000.0, 950.0) is False  # over target fails


def test_dnr_dpmo_is_not_evaluated_as_higher_is_better():
    """The specific inversion, stated as its own case.

    An excellent DNR DPMO (400 against a 950 ceiling) must PASS, and a
    catastrophic one (9000) must FAIL. A `value >= target` implementation
    produces exactly the opposite and looks plausible doing it.
    """
    assert meets_target("dnr_dpmo", 400.0, 950.0) is True
    assert meets_target("dnr_dpmo", 9000.0, 950.0) is False


# ---------------------------------------------------------------------------
# Map integrity
# ---------------------------------------------------------------------------

def test_unknown_metric_key_raises():
    """A new metric cannot be compared until someone states its direction."""
    with pytest.raises(KeyError):
        meets_target("brand_new_metric", 1.0, 1.0)


def test_every_metric_has_a_target_field_and_vice_versa():
    """The two maps must not drift — a metric with a direction but no target
    column is uncomparable, and a target column with no direction is unusable."""
    assert set(METRIC_DIRECTION) == set(METRIC_TARGET_FIELD)


def test_every_direction_is_a_known_value():
    assert set(METRIC_DIRECTION.values()) <= {"higher", "lower"}


def test_target_fields_exist_on_the_model():
    """Guards against a typo in METRIC_TARGET_FIELD that would make target_for()
    silently return None — which callers read as 'no target configured' rather
    than as a bug."""
    from app.models.company import CompanyConfig

    for key, field in METRIC_TARGET_FIELD.items():
        assert hasattr(CompanyConfig, field), f"{key} -> missing column {field}"


def test_resolved_config_target_for_returns_none_when_unset():
    """NULL means 'no target configured'. It must never render as a failure —
    callers show the reported value with no pass/fail judgement."""
    from app.services.company_config import ResolvedConfig
    import dataclasses

    fields = {f.name: None for f in dataclasses.fields(ResolvedConfig)}
    cfg = ResolvedConfig(**fields)

    for key in METRIC_TARGET_FIELD:
        assert cfg.target_for(key) is None
