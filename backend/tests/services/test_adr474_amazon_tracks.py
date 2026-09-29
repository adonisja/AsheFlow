"""Amazon knows two roles; we project ours onto them (ADR-474).

ADR-473 made targets storable with the right shape and did not ask WHO a target
applies to. Comparing a walker against a speeding ceiling does not error -- it
returns a verdict about nothing, which is the same silent wrongness ADR-473
spent a day removing.

The design turns on one fact from the operator: "Amazon only acknowledges 2
roles, drivers and walkers, while the DSPs have their own breakdowns." So this
is a PROJECTION done once, not an applies_to list restated across ten roles.
"""
import pytest

from app.models.employee import VALID_ROLES
from app.services.company_config import (
    AMAZON_TRACK,
    METRIC_SHAPES,
    amazon_track,
    expected_for_role,
    meets_target,
)

SAFETY = ("fico", "speeding_rate", "signsignal_rate",
          "seatbelt_rate", "distractions_rate", "following_distance_rate")
SHARED = ("pod", "dsb_dpmo", "cdf_dpmo", "dc_dpmo", "fleet_execution",
          "ces_dpmo", "cdf_negative")


# ── D1: the projection is total ─────────────────────────────────────────────

def test_every_role_has_a_track():
    """A role added later without a track must be a collection error, not a
    silent walker."""
    missing = sorted(set(VALID_ROLES) - set(AMAZON_TRACK))
    assert not missing, f"roles with no Amazon track: {missing}"


def test_the_projection_invents_no_roles():
    extra = sorted(set(AMAZON_TRACK) - set(VALID_ROLES))
    assert not extra, f"AMAZON_TRACK maps roles that do not exist: {extra}"


def test_only_amazons_two_roles_are_used():
    assert set(AMAZON_TRACK.values()) <= {"walker", "driver", None}


@pytest.mark.parametrize("role", ["walker", "captain", "trainer", "trainee"])
def test_the_walking_track(role):
    """Captain and trainer are the surprising two, and neither is a guess: a
    captain runs the ground operation on foot, and a trainer trains walkers."""
    assert amazon_track(role) == "walker"


@pytest.mark.parametrize("role", [
    "driver", "driver_trainee", "dispatch", "management", "admin",
    "field_supervisor",
])
def test_the_driving_track(role):
    """The office roles included deliberately. dispatch/management/admin get no
    route assignment from AsheFlow, but an owner covering a call-out is a DA to
    Amazon with their own card -- this decides whose card is whose on ingest,
    not who we dispatch."""
    assert amazon_track(role) == "driver"


def test_the_two_training_tracks_do_not_collide():
    """ADR-264 split them; the projection must keep them split."""
    assert amazon_track("trainee") == "walker"
    assert amazon_track("driver_trainee") == "driver"


# ── D2: an undecided role raises, never defaults ────────────────────────────

def test_an_unmapped_role_raises_rather_than_defaulting():
    """THE invariant, and it outlives any particular role. Six of ten map to
    driver, so "default to driver" is always the tempting guess -- and a wrong
    track is a silent verdict on metrics the person is not measured on."""
    original = AMAZON_TRACK.get("walker")
    AMAZON_TRACK["walker"] = None
    try:
        with pytest.raises(ValueError) as exc:
            amazon_track("walker")
        assert "unmapped" in str(exc.value) or "decided" in str(exc.value)
    finally:
        AMAZON_TRACK["walker"] = original


def test_an_unknown_role_raises():
    with pytest.raises(ValueError):
        amazon_track("astronaut")


def test_the_raise_says_what_to_do():
    """A bare failure gets defaulted around; one naming the decision gets made."""
    with pytest.raises(ValueError) as exc:
        amazon_track("astronaut")
    assert "AMAZON_TRACK" in str(exc.value)


# ── D3: metrics declare their tracks ────────────────────────────────────────

def test_every_metric_declares_expected_for():
    for key, shape in METRIC_SHAPES.items():
        assert "expected_for" in shape, f"{key} does not say who is expected to have it"
        assert set(shape["expected_for"]) <= {"walker", "driver"}, key
        assert shape["expected_for"], f"{key} is expected for nobody"


@pytest.mark.parametrize("key", SAFETY)
def test_safety_metrics_are_expected_for_drivers_only(key):
    """A walker has no vehicle to generate telematics, so an empty safety tile
    on a walker card is unremarkable.

    EXPECTED, not exclusive: a real walker card renders all six of these reading
    "No Data". This field predicts absence; it does not decide layout.
    """
    assert METRIC_SHAPES[key]["expected_for"] == ("driver",)


@pytest.mark.parametrize("key", SHARED)
def test_quality_metrics_are_expected_for_both(key):
    assert set(METRIC_SHAPES[key]["expected_for"]) == {"walker", "driver"}


def test_every_metric_is_classified_by_the_test_too():
    """Guards the test's own lists against drift: a metric added to the registry
    and to neither list here would be silently unasserted."""
    assert set(SAFETY) | set(SHARED) == set(METRIC_SHAPES)


# ── D4: comparing outside a track raises ────────────────────────────────────

def test_an_absent_value_is_refused():
    """Not False and not True. A 'fail' and a 'pass' computed from nothing are
    equally wrong, and the pass is worse -- nobody investigates a pass."""
    with pytest.raises(ValueError) as exc:
        meets_target("speeding_rate", None, 8.0)
    assert "no measurement" in str(exc.value)


def test_an_absent_value_is_refused_whatever_the_role():
    """The correction. Keying on track failed in BOTH directions: a driver whose
    tile reads "No Data" would have got a verdict computed from nothing."""
    for role in ("walker", "driver"):
        with pytest.raises(ValueError):
            meets_target("speeding_rate", None, 8.0, role=role)


def test_a_walker_WITH_a_reading_is_compared_not_refused():
    """The other direction, and the one a real walker card exposed. Every safety
    metric renders on a walker card; if one carries a value, refusing to compare
    it withholds a verdict the person earned."""
    assert meets_target("speeding_rate", 6.0, 8.0, role="walker") is True
    assert meets_target("speeding_rate", 12.0, 8.0, role="walker") is False


def test_expectation_is_a_hint_not_a_gate():
    """A captain is a walker to Amazon, so a FICO reading is unexpected -- and
    unexpected is not impossible. The hint explains an empty tile; it never
    decides whether a comparison may run."""
    assert expected_for_role("fico", "captain") is False
    assert meets_target("fico", 810, 800, role="captain") is True


def test_a_driver_is_compared_normally_on_a_driver_metric():
    assert meets_target("speeding_rate", 6.0, 8.0, role="driver") is True
    assert meets_target("speeding_rate", 12.0, 8.0, role="driver") is False


def test_both_tracks_are_compared_on_a_shared_metric():
    for role in ("walker", "driver"):
        assert meets_target("pod", 99.0, 98.0, role=role) is True
        assert meets_target("pod", 97.0, 98.0, role=role) is False


def test_omitting_the_role_still_works_for_company_figures():
    """A company-level comparison has no person, so there is no track to check."""
    assert meets_target("fico", 810, 800) is True
    assert meets_target("speeding_rate", 6.0, 8.0) is True


def test_direction_still_applies_inside_a_track():
    """D4 must not swallow ADR-473's direction handling."""
    assert meets_target("dsb_dpmo", 200, 233, role="walker") is True
    assert meets_target("dsb_dpmo", 300, 233, role="walker") is False


def test_expected_for_role_rejects_a_retired_metric_by_name():
    with pytest.raises(ValueError) as exc:
        expected_for_role("dcr", "driver")
    assert "dc_dpmo" in str(exc.value)


# ── D5/D6: targets stay company-wide ────────────────────────────────────────

def test_the_target_table_has_no_track_column():
    """Amazon sets thresholds per programme, not per person: a walker and a
    driver at the same DSP share the same DSB ceiling. What differs is which
    metrics are ASKED, not what the answer is."""
    from app.models.metric_target import CompanyMetricTarget

    cols = set(CompanyMetricTarget.__table__.columns.keys())
    assert "track" not in cols and "role" not in cols


# ── the correction, pinned to the evidence that forced it ───────────────────

def test_no_metric_is_excluded_by_track():
    """A real walker card renders ALL SIX safety metrics, reading "No Data".

    Amazon does not omit them; it reports that there is nothing to report. So
    nothing in the registry may say a metric is unavailable to a track -- only
    that data is not expected. Pinned because the first version of this ADR
    asserted the opposite, from the guides rather than from a card.
    """
    for key, shape in METRIC_SHAPES.items():
        assert "applies_to" not in shape, (
            f"{key} still claims to decide availability by track; "
            "expected_for predicts data, it does not decide layout"
        )


def test_meets_target_does_not_gate_on_role():
    """The refusal must key on value presence, not on the person's track.

    Keying on track fails both ways: it withholds a verdict from a walker who
    has a reading, and computes one for a driver whose tile is empty.
    """
    import inspect

    from app.services import company_config

    src = inspect.getsource(company_config.meets_target)
    code = "\n".join(
        l for l in src.splitlines()
        if not l.strip().startswith("#") and '"""' not in l
    )
    assert "if value is None:" in code
    assert "expected_for_role(key, role)" not in code, (
        "the comparison gates on expectation again"
    )


def test_a_count_unit_is_allowed():
    """CDF-Negative is a bare count on the card, not a rate or a percentage.

    Without its own unit it would have to borrow one, and borrowing `percent`
    would cap a count at 100 -- the same defect ADR-473 fixed on CDF.
    """
    from app.models.metric_target import VALID_UNITS

    assert "count" in VALID_UNITS
    assert METRIC_SHAPES["cdf_negative"]["unit"] == "count"


def test_the_two_card_metrics_added_from_real_cards_are_present():
    """Confirmed on both the walker and driver card, 2026-09-29."""
    for key in ("ces_dpmo", "cdf_negative"):
        assert key in METRIC_SHAPES
        assert METRIC_SHAPES[key]["direction"] == "lower"
