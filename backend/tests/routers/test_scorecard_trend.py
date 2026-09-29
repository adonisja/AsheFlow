"""Company scorecard trend — value parsing and direction correctness.

Amazon stores scorecard values as DISPLAY STRINGS ("100.0%", "14492.7",
"PLATINUM", "1,234"), so the trend has to parse them, and some metrics invert:
for DPMO and driver-behaviour rates a HIGHER number is WORSE. Getting that
backwards would paint a worsening week as an improvement — the most dangerous
possible bug in a page whose whole job is telling you which way things moved.
"""
from app.routers.scorecards import _numeric, _iter_weeks, _is_lower_better


class TestValueParsing:
    def test_percentage(self):
        assert _numeric("100.0%") == 100.0
        assert _numeric("98.7%") == 98.7

    def test_plain_and_decimal(self):
        assert _numeric("203") == 203.0
        assert _numeric("14492.7") == 14492.7

    def test_thousands_separator(self):
        """Amazon prints large counts with commas; float() rejects those."""
        assert _numeric("1,234") == 1234.0
        assert _numeric("14,492.7") == 14492.7

    def test_tier_words_are_not_numbers(self):
        """None is a real answer — tiers chart as standings, not a line."""
        assert _numeric("PLATINUM") is None
        assert _numeric("Fantastic") is None

    def test_blank_and_none(self):
        assert _numeric("") is None
        assert _numeric(None) is None


class TestDirectionSemantics:
    """Re-pointed by ADR-475 D1. The intent below is unchanged and is the reason
    this file exists; what changed is where the answer comes from.

    It used to assert membership of `_LOWER_IS_BETTER`, a hand-maintained set
    whose keys -- `dnr_dpmo`, `seatbelt_off_rate`, `speeding_event_rate` --
    matched NOTHING: not the registry, not the ingestor, not the entry template.
    A FOURTH vocabulary. So the set was internally consistent, passed these
    tests, and could not classify a single metric the app actually stored: every
    real key fell through to higher-is-better, including every DPMO.

    Direction is now derived from METRIC_SHAPES, so these assert the behaviour
    against the keys the system really uses.
    """

    def test_dpmo_is_lower_is_better(self):
        """A DPMO rising is a REGRESSION, not an improvement."""
        for k in ("dsb_dpmo", "cdf_dpmo", "dc_dpmo", "ces_dpmo"):
            assert _is_lower_better(k), k

    def test_driver_behaviour_rates_invert(self):
        for k in ("seatbelt_rate", "speeding_rate", "distractions_rate",
                  "signsignal_rate", "following_distance_rate"):
            assert _is_lower_better(k), k

    def test_delivery_rates_are_higher_is_better(self):
        """POD and FICO: more is better, so a rise is an improvement."""
        for k in ("pod", "fico"):
            assert not _is_lower_better(k), k

    def test_an_unknown_key_does_not_claim_to_know(self):
        """Falls back to higher-is-better rather than raising, because a trend
        arrow is decoration: refusing to draw the page over an unrecognised row
        is worse than drawing one arrow conservatively."""
        assert not _is_lower_better("a_metric_nobody_registered")

    def test_every_registered_metric_is_classified(self):
        """The old set's real failure: it silently did not cover the keys in
        use. This makes that impossible to repeat."""
        from app.services.company_config import METRIC_SHAPES

        for key, shape in METRIC_SHAPES.items():
            assert _is_lower_better(key) == (shape["direction"] == "lower"), key


class TestWeekEnumeration:
    def test_same_year_range(self):
        assert _iter_weeks("2026-W01", "2026-W04") == [
            "2026-W01", "2026-W02", "2026-W03", "2026-W04"]

    def test_year_rollover(self):
        wks = _iter_weeks("2025-W52", "2026-W02")
        assert wks[0] == "2025-W52"
        assert "2026-W01" in wks
        assert wks[-1] == "2026-W02"

    def test_single_week(self):
        assert _iter_weeks("2026-W10", "2026-W10") == ["2026-W10"]

    def test_malformed_label_returns_empty(self):
        """A bad label must not hang the 400-iteration loop or raise."""
        assert _iter_weeks("garbage", "2026-W02") == []
        assert _iter_weeks("2026-W01", "nonsense") == []

    def test_gap_detection_is_the_point(self):
        """Enumeration exists so a missing week shows as a gap rather than
        silently closing up in the chart."""
        expected = _iter_weeks("2026-W01", "2026-W05")
        present = {"2026-W01", "2026-W02", "2026-W05"}
        assert [w for w in expected if w not in present] == ["2026-W03", "2026-W04"]
