"""One vocabulary, and "No Data" is not zero (ADR-475).

The scorecard surface predates the metric registry and disagreed with it four
ways: a parallel key vocabulary, a label map from one station, rows dropped when
unrecognised, and "No Data" rendered as a dash.

The key fact that made D1 cheap: prod held NO scorecards, so unifying the
vocabulary is a rename rather than a data migration. That window closes the
moment a real card is saved.
"""
import inspect
import pathlib
import re

import pytest

from app.services import scorecard_ingestor as SI
from app.services.company_config import METRIC_SHAPES, RETIRED_METRICS

ROOT = pathlib.Path(__file__).resolve().parents[3]
ENTRY = ROOT / "frontend/src/pages/ScorecardEntry.tsx"
PANEL = ROOT / "frontend/src/components/MyScorecardPanel.tsx"


# ── D1: one vocabulary ──────────────────────────────────────────────────────

def test_every_ingestor_key_is_a_registry_key():
    """The defect this ADR exists for: zero of nine template keys existed in
    the registry, so a stored target could never match an ingested metric."""
    keys = {k for _, k in SI._LABEL_KEYS}
    unknown = sorted(keys - set(METRIC_SHAPES) - SI.CONTEXT_KEYS)
    assert not unknown, f"ingestor keys not in the registry: {unknown}"


def test_no_retired_key_is_ingested():
    keys = {k for _, k in SI._LABEL_KEYS}
    assert not (keys & set(RETIRED_METRICS))


def test_every_entry_template_key_is_a_registry_key():
    src = ENTRY.read_text()
    block = src.split("const TEMPLATE", 1)[1].split("\n];", 1)[0]
    keys = set(re.findall(r"key:\s*'([a-z0-9_]+)'", block))
    unknown = sorted(keys - set(METRIC_SHAPES) - SI.CONTEXT_KEYS)
    assert not unknown, f"entry template keys not in the registry: {unknown}"


def test_the_entry_template_and_the_ingestor_agree():
    """Two surfaces, one vocabulary. They drifted before precisely because
    nothing compared them."""
    src = ENTRY.read_text()
    block = src.split("const TEMPLATE", 1)[1].split("\n];", 1)[0]
    template = set(re.findall(r"key:\s*'([a-z0-9_]+)'", block))
    ingestor = {k for _, k in SI._LABEL_KEYS}
    assert template == ingestor, (
        f"only in template: {sorted(template - ingestor)}; "
        f"only in ingestor: {sorted(ingestor - template)}"
    )


# ── D2: labels from real cards ──────────────────────────────────────────────

def test_safe_driving_metric_maps_to_fico():
    """The entry that proves the map must come from cards: Amazon labels FICO
    "Safe Driving Metric", with "FICO" only as a sub-label. Nothing searching
    for the word would find it."""
    assert SI._key_for_label("Safe Driving Metric") == "fico"


@pytest.mark.parametrize("label,key", [
    ("Seatbelt-Off Rate",                     "seatbelt_rate"),
    ("Speeding Event Rate",                   "speeding_rate"),
    ("Distractions Rate",                     "distractions_rate"),
    ("Following Distance Rate",               "following_distance_rate"),
    ("Sign/Signal Violations",                "signsignal_rate"),
    ("Delivery Completion DPMO",              "dc_dpmo"),
    ("Delivery Success Behaviors",            "dsb_dpmo"),
    ("Customer Escalations Defect",           "ces_dpmo"),
    ("POD Acceptance Rate",                   "pod"),
])
def test_real_card_labels_map(label, key):
    assert SI._key_for_label(label) == key


def test_the_negative_feedback_label_is_not_swallowed_by_the_dpmo_one():
    """Substring matching is order-dependent: "customer delivery feedback"
    is a prefix of the negative label, so the longer one must come first or
    the count is read as the DPMO."""
    assert SI._key_for_label("Customer Delivery Feedback - Negative") == "cdf_negative"
    assert SI._key_for_label("Customer Delivery Feedback (CDF DPMO)") == "cdf_dpmo"


def test_the_safety_half_is_no_longer_lost():
    """The old map knew nine labels from one station and no safety metric at
    all, so a driver's card lost its entire safety section."""
    keys = {k for _, k in SI._LABEL_KEYS}
    for key in ("fico", "seatbelt_rate", "speeding_rate", "distractions_rate",
                "following_distance_rate", "signsignal_rate"):
        assert key in keys, key


# ── D3: nothing is silently dropped ─────────────────────────────────────────

def test_an_unrecognised_row_is_kept():
    src = inspect.getsource(SI.ScorecardIngestor)
    code = "\n".join(
        l for l in src.splitlines() if not l.strip().startswith("#")
    )
    assert "if key is None and not label:" in code, (
        "the parser drops unrecognised rows again"
    )


def test_the_draft_metric_key_is_optional():
    """Typed `str` before, while the parser could already produce None -- the
    annotation said the drop could not happen and the code did it anyway."""
    assert SI.ScorecardDraftMetric.__annotations__["key"] == "Optional[str]"


def test_an_unrecognised_row_is_not_guessed_into_a_key():
    m = SI.ScorecardDraftMetric(key=None, label="Gibberish", value="7")
    assert m.recognised is False


def test_the_draft_response_can_carry_a_null_key():
    """Reusing ScorecardMetricIn for the draft is what made the drop
    unavoidable: its `key` is required, so a row without one could not be
    represented and the parser dropped it rather than failing."""
    from app.schemas.scorecard import ScorecardDraftMetricOut, ScorecardMetricIn

    ScorecardDraftMetricOut(key=None, label="Gibberish", value="7")
    assert ScorecardMetricIn.model_fields["key"].is_required(), (
        "an unnamed row must still be refused on SAVE"
    )


def test_the_draft_reports_how_many_rows_it_could_not_name():
    """A count, so the reviewer is told rather than having to notice."""
    from app.schemas.scorecard import ScorecardDraftOut

    assert "unrecognised_count" in ScorecardDraftOut.model_fields


# ── D4: "No Data" is not zero ───────────────────────────────────────────────

def test_no_data_is_recognised_as_an_absence():
    for text in ("No Data", "no data", "  No Data  ", "N/A", ""):
        assert SI.is_no_data(text), text


def test_a_zero_is_not_an_absence():
    """A zero seatbelt rate is PERFECT. Conflating it with "No Data" makes an
    unmeasured walker look flawless -- the inversion ADR-473 spent a day
    removing."""
    for text in ("0", "0.0", "0.00%"):
        assert not SI.is_no_data(text), text


def test_the_trend_dto_distinguishes_three_states():
    from app.schemas.scorecard import MetricTrend

    assert "measured" in MetricTrend.model_fields
    assert MetricTrend.model_fields["measured"].default is None


def test_the_panel_renders_no_data_distinctly_from_a_dash():
    src = PANEL.read_text()
    assert "NO_DATA_LABEL" in src
    assert "m.measured === false" in src


# ── the fourth vocabulary, removed ──────────────────────────────────────────

def test_trend_direction_comes_from_the_registry():
    """`_LOWER_IS_BETTER` was a FOURTH vocabulary -- `dnr_dpmo`,
    `seatbelt_off_rate`, `sign_signal_violations_rate` -- matching nothing the
    app stored. It was internally consistent, passed its tests, and classified
    not one real metric: every DPMO fell through to higher-is-better, so a
    worsening week drew an improving arrow."""
    from app.routers import scorecards

    src = inspect.getsource(scorecards)
    assert "_LOWER_IS_BETTER" not in src
    for key, shape in METRIC_SHAPES.items():
        assert scorecards._is_lower_better(key) == (shape["direction"] == "lower"), key
