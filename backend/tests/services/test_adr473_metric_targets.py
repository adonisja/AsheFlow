"""Scorecard targets must match Amazon's metrics (ADR-473).

Ten `CompanyConfig.scorecard_*_target` columns asserted a comparison direction
and a unit in COMMENTS. Checked against Amazon's own metric resource guides,
five asserted them wrong:

    cdf   modelled %, higher better, capped at 100  -> a DPMO, LOWER better
    dcr   modelled %, higher better                 -> a defect rate, LOWER better
    dvic  modelled completion %                     -> inspection QUALITY, lower better
    cc    modelled %, higher better                 -> not a scored metric at all
    dnr   modelled as its own DPMO                  -> counted inside DSB

`meets_target` had no callers, so nothing produced a wrong verdict -- this is a
correctness fix BEFORE the wiring, which is the only reason it could be designed
rather than hot-fixed.
"""
import inspect
import pathlib
import re

import pytest

from app.models.metric_target import (
    VALID_DIRECTIONS, VALID_UNITS, CompanyMetricTarget,
)
from app.services import company_config as CC

ROOT = pathlib.Path(__file__).resolve().parents[3]


# ── D1: targets are rows ────────────────────────────────────────────────────

def test_the_hardcoded_columns_are_gone():
    """All ten, not just the five that were wrong. Keeping the correct five as
    columns would leave the same trap armed for the next reshape."""
    for path in ("backend/app/models/company.py",
                 "backend/app/routers/companies.py",
                 "backend/app/services/company_config.py",
                 "frontend/src/pages/CompanySettings.tsx"):
        src = (ROOT / path).read_text()
        found = re.findall(r"scorecard_\w+_target\s*[:=]", src)
        assert not found, f"{path} still defines {found}"


def test_the_table_mirrors_the_ingestion_side():
    """ScorecardMetric was already key/value with a unit, which is why it
    absorbed Amazon's changes while the columns diverged."""
    cols = set(CompanyMetricTarget.__table__.columns.keys())
    assert {"company_id", "metric_key", "target_value", "direction", "unit"} <= cols


def test_company_id_is_stamped_not_only_joined():
    """Dimension 1. A query starting from this table must have a company_id to
    filter on -- the same reasoning ScorecardMetric records."""
    assert CompanyMetricTarget.__table__.columns["company_id"].nullable is False


def test_one_target_per_metric_per_company():
    names = {c.name for c in CompanyMetricTarget.__table__.constraints}
    assert "uq_company_metric_targets_company_key" in names


# ── D2: direction and unit stored, never inferred ───────────────────────────

def test_direction_and_unit_are_not_nullable():
    """A target whose direction nobody stated is a comparison waiting to be
    made backwards, which is the defect this table exists to prevent."""
    for col in ("direction", "unit"):
        assert CompanyMetricTarget.__table__.columns[col].nullable is False


def test_meets_target_reads_the_direction_it_is_given():
    """THE fix. The old version looked up a hardcoded map; a company whose
    stored shape differs must be judged by its own row."""
    assert CC.meets_target("x", value=5, target=10, direction="lower") is True
    assert CC.meets_target("x", value=15, target=10, direction="lower") is False
    assert CC.meets_target("x", value=15, target=10, direction="higher") is True
    assert CC.meets_target("x", value=5, target=10, direction="higher") is False


def test_an_unreadable_direction_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        CC.meets_target("pod", 99, 98, direction="sideways")


def test_a_dpmo_passes_when_lower():
    """The inverted case that started this ADR: CDF was modelled as a percentage
    where higher passes, and is a DPMO where lower passes."""
    assert CC.meets_target("cdf_dpmo", value=900, target=980) is True
    assert CC.meets_target("cdf_dpmo", value=1100, target=980) is False


def test_every_registered_metric_has_a_valid_shape():
    for key, shape in CC.METRIC_SHAPES.items():
        assert shape["direction"] in VALID_DIRECTIONS, key
        assert shape["unit"] in VALID_UNITS, key


# ── D3: retired keys fail loudly ────────────────────────────────────────────

@pytest.mark.parametrize("key", ["dcr", "cdf", "dvic", "cc", "dnr_dpmo"])
def test_a_retired_metric_names_what_replaced_it(key):
    """A bare KeyError reads like a typo. These are deliberate removals and the
    error has to say so, or someone re-adds the column."""
    with pytest.raises(ValueError) as exc:
        CC.meets_target(key, 1, 1)
    assert key in str(exc.value)
    assert len(str(exc.value)) > 40, "the reason is missing"


def test_no_retired_key_is_also_a_live_shape():
    assert not (set(CC.RETIRED_METRICS) & set(CC.METRIC_SHAPES))


# ── D4: the safety metrics we did not model ─────────────────────────────────

def test_the_missing_safety_rates_are_registered():
    """Seatbelt, distractions and following-distance outweigh the two rates we
    already carried, so a tenant tuning only speeding and sign/signal was tuning
    the minority of the safety score."""
    for key in ("seatbelt_rate", "distractions_rate", "following_distance_rate"):
        assert key in CC.METRIC_SHAPES, f"{key} still has no shape"
        assert CC.METRIC_SHAPES[key]["direction"] == "lower"


# ── D5: no Amazon thresholds in the repo ────────────────────────────────────

def test_no_threshold_figures_are_stored_in_code():
    """Amazon revises them, they are commercially sensitive, and the DSP Program
    Agreement obliges the tenant to protect them. A seeded default would put
    their competitive bars in a git history."""
    targets = [
        ROOT / "backend/app/services/company_config.py",
        ROOT / "backend/app/models/metric_target.py",
    ]
    targets += list((ROOT / "backend/alembic/versions").glob("*adr473*.py"))
    for path in targets:
        src = path.read_text()
        for figure in ("233", "429", "980", "1115", "3900", "3,900"):
            assert figure not in src, f"{path.name} carries the threshold {figure}"


def test_the_migration_carries_shapes_not_values():
    mig = next((ROOT / "backend/alembic/versions").glob("*adr473*.py"))
    src = mig.read_text()
    assert "_CARRIED" in src and "_CLEARED" in src
    # the five wrong ones are cleared, not converted
    for key in ("dcr", "cdf", "cc", "dnr_dpmo", "dvic"):
        assert f"scorecard_{key}_target" in src.split("_CLEARED", 1)[1], key


def test_the_migration_reports_what_it_did():
    """A silent data migration on a config table is not something to discover
    later (ADR-468 precedent)."""
    mig = next((ROOT / "backend/alembic/versions").glob("*adr473*.py"))
    src = mig.read_text()
    assert "print(" in src
    assert "cleared" in src


def test_the_migration_is_self_contained():
    import ast
    mig = next((ROOT / "backend/alembic/versions").glob("*adr473*.py"))
    for node in ast.walk(ast.parse(mig.read_text())):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", None) or node.names[0].name
            assert not str(name).startswith("app."), f"imports {name}"
