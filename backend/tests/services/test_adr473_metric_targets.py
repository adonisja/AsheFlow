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
    # The DOCS too. Two thresholds reached this ADR and its journal while they
    # were being written -- a verification step quoting a real figure reads as
    # harmless and is the same leak. docs/ is gitignored from the public repo
    # but syncs to AsheFlow-private, which is still a durable store.
    for d in ("docs/decisions", "docs/journals"):
        targets += list((ROOT / d).glob("*473*")) + list((ROOT / d).glob("*Targets-Become-Rows*"))
    targets = [t for t in targets if t.exists()]
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


# ── D6: the surface (endpoints + client) ────────────────────────────────────

def _router_src() -> str:
    from app.routers import companies
    return inspect.getsource(companies)


def test_the_endpoints_exist_and_are_admin_only():
    """Targets decide whether a person's week passes. That is not a dispatch
    setting."""
    from app.routers import companies

    for fn in ("list_metric_targets", "upsert_metric_target", "delete_metric_target"):
        src = inspect.getsource(getattr(companies, fn))
        assert "allow_admin" in src, f"{fn} is not admin-gated"


def test_every_target_query_is_company_scoped():
    """Dimension 1. Three queries, three filters."""
    from app.routers import companies

    for fn in ("list_metric_targets", "upsert_metric_target", "delete_metric_target"):
        src = inspect.getsource(getattr(companies, fn))
        assert "CompanyMetricTarget.company_id == caller.company_id" in src, fn


def test_direction_and_unit_are_never_accepted_from_the_client():
    """THE defect ADR-473 closed, restated at the trust boundary: a caller who
    can set the direction can have their metric compared backwards."""
    from app.routers.companies import MetricTargetUpsert

    fields = set(MetricTargetUpsert.model_fields)
    assert "direction" not in fields
    assert "unit" not in fields
    assert fields == {"metric_key", "target_value"}


def test_the_upsert_schema_forbids_extra_keys():
    """A misspelled field would otherwise be a silent no-op that looks saved."""
    from app.routers.companies import MetricTargetUpsert

    assert MetricTargetUpsert.model_config.get("extra") == "forbid"


def test_the_shape_comes_from_the_registry():
    src = inspect.getsource(
        __import__("app.routers.companies", fromlist=["x"])._shape_for
    )
    assert "METRIC_SHAPES" in src and "RETIRED_METRICS" in src


def test_a_retired_metric_is_refused_with_its_reason():
    """Not a bare 422. An Owner reading 'dcr is not valid' re-enters it; one
    reading what replaced it sets the right field."""
    from app.routers.companies import _shape_for
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _shape_for("dcr")
    assert exc.value.status_code == 422
    assert "dc_dpmo" in str(exc.value.detail)


def test_an_unknown_metric_is_refused():
    from app.routers.companies import _shape_for
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _shape_for("invented_metric")
    assert exc.value.status_code == 422


def test_percent_bounds_follow_the_unit_not_every_field():
    """The old schema put le=100.0 on all ten, which is why a real DPMO could
    not be stored. The bound now applies only where the unit is a percentage."""
    src = inspect.getsource(
        __import__("app.routers.companies", fromlist=["x"]).upsert_metric_target
    )
    # Strip comments: the explanation NAMES the old `le=100.0`, and matching on
    # prose rather than code failed the first version of this test against
    # correct code. Third time this session, hence the note.
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert 'shape["unit"] == "percent"' in code
    assert "le=100" not in code


def test_writes_are_audited():
    from app.routers import companies

    for fn, action in (("upsert_metric_target", "metric_target.upsert"),
                       ("delete_metric_target", "metric_target.delete")):
        src = inspect.getsource(getattr(companies, fn))
        assert f'action_type="{action}"' in src, fn


def test_the_upsert_follows_flush_audit_commit():
    src = inspect.getsource(
        __import__("app.routers.companies", fromlist=["x"]).upsert_metric_target
    )
    assert src.index("db.flush()") < src.index("write_audit") < src.index("db.commit()")


def test_delete_returns_a_count_not_a_silent_204():
    """A silent success after a destructive action is how someone runs it
    twice."""
    src = inspect.getsource(
        __import__("app.routers.companies", fromlist=["x"]).delete_metric_target
    )
    assert '"deleted"' in src


def test_the_routes_are_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/companies/my-config/metric-targets" in paths
    assert "/api/v1/companies/my-config/metric-targets/{metric_key}" in paths


# ── D6: the client ──────────────────────────────────────────────────────────

SETTINGS = ROOT / "frontend/src/pages/CompanySettings.tsx"
TYPES = ROOT / "frontend/src/api/types.ts"


def test_the_endpoint_has_a_caller():
    """ADR-381. The gap this ADR named was a table with no surface; shipping one
    with no caller would be the same gap one layer up."""
    src = SETTINGS.read_text()
    assert "'/companies/my-config/metric-targets'" in src


def test_the_client_never_sends_direction_or_unit():
    src = SETTINGS.read_text()
    body = src.split("axiosClient.put('/companies/my-config/metric-targets'", 1)[1]
    body = body.split("}", 2)[0] + "}"
    assert "direction" not in body and "unit" not in body


def test_the_ui_reads_direction_from_the_server_row():
    """A hardcoded direction in the client would be the ADR-473 defect moved to
    the frontend."""
    src = SETTINGS.read_text()
    assert "const dir = row?.direction" in src
    block = src.split("const KNOWN_METRICS", 1)[1].split("];", 1)[0]
    assert "direction" not in block, "KNOWN_METRICS hardcodes a direction"


def test_clearing_a_target_deletes_rather_than_saving_zero():
    """An unset target means 'report without a verdict', not 'the target is
    zero' -- ADR-262's rule, and a zero ceiling fails everyone."""
    src = SETTINGS.read_text()
    block = src.split("const saveTarget", 1)[1].split("};", 1)[0]
    assert "axiosClient.delete" in block
    assert "raw.trim() === ''" in block


def test_the_section_is_hidden_during_onboarding():
    """A DSP setting the platform up has not read their first Amazon card, and
    a page asking for numbers they cannot have is a page they abandon."""
    # Anchor on the SECTION, not the first place the words appear -- an ADR
    # comment above mentions them and made the first version of this test pass
    # on unrelated text.
    src = SETTINGS.read_text()
    i = src.index("{/* ---- Scorecard targets (ADR-473 D6")
    assert "!isOnboarding && (" in src[i:i + 200]


def test_the_ts_type_mirrors_the_response():
    from app.routers.companies import MetricTargetOut

    ts = TYPES.read_text()
    block = ts.split("export interface MetricTarget {", 1)[1].split("}", 1)[0]
    for field in MetricTargetOut.model_fields:
        assert field in block, f"{field} missing from the TS type"


def test_the_migration_reads_the_table_the_columns_live_on():
    """CAUGHT BY CI, not by me.

    The ten columns live on `company_configs`, not `companies` -- two models in
    one module, which is the exact D3 trap CLAUDE.md names. My scratch test
    seeded a hand-made `companies` table, so it reproduced my mistake instead of
    catching it: a harness that builds its own schema tests the schema it built.

    The fresh-database CI job found it because it runs every migration from
    empty against the real schema.
    """
    mig = next((ROOT / "backend/alembic/versions").glob("*adr473*.py"))
    src = mig.read_text()
    body = "\n".join(
        l for l in src.splitlines()
        if not l.strip().startswith("#") and '"""' not in l
    )
    assert "FROM company_configs" in body
    assert "FROM companies " not in body, "reading the wrong table again"
    assert 'op.drop_column("company_configs"' in body
    assert 'op.drop_column("companies"' not in body


def test_the_columns_are_actually_gone_from_the_orm():
    """The complement: the migration and the model must agree about which class
    lost the columns."""
    from app.models.company import Company, CompanyConfig

    for cls in (Company, CompanyConfig):
        leftover = [c for c in cls.__table__.columns.keys() if "scorecard_" in c]
        assert not leftover, f"{cls.__name__} still has {leftover}"
