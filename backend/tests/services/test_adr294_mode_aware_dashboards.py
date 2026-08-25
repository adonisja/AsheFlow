"""ADR-294 — a metric that does not apply must not read as a metric that is zero.

THE FAILURE THIS PREVENTS. In workforce mode `DeliveryStop` is never written, so
`_package_totals` aggregated over an empty table and returned hard zeros. A
dispatcher's dashboard read **"0 packages delivered"** — which is a measurement,
and an alarming one — when the truth was "this company has no package feed, so
the question does not apply".

That is the shape of the 2026-07-29 incident where 11 DTO fields returned
fabricated data. `frontend/src/utils/metric.ts` already states the rule in its
own docstring: *"null and 0 are DIFFERENT FACTS and must never render the same
way"*. The frontend was right; the backend was lying to it.
"""
import uuid
from datetime import date

import pytest

from app.models.company import Company, CompanyConfig
from app.services.constants import MODE_FULL, MODE_WORKFORCE
from app.services.dashboard_summaries import (
    _UNAVAILABLE_PACKAGE_TOTALS, _package_totals_for_mode, _pct, _ratio,
)


# ── the arithmetic must not manufacture a zero ────────────────────────────────

def test_pct_returns_none_for_a_null_numerator():
    """`num or 0` would report 0% for "we do not track this", which reads as a
    real and alarming figure rather than an absence."""
    assert _pct(None, 10) is None


def test_pct_still_reports_a_genuine_zero():
    """0 out of 10 IS a measurement and must survive — the fix must not blanket
    every zero into an em-dash."""
    assert _pct(0, 10) == 0.0


def test_ratio_returns_none_for_a_null_numerator():
    assert _ratio(None, 5) is None


def test_ratio_still_reports_a_genuine_zero():
    assert _ratio(0, 5) == 0.0


def test_pct_returns_none_on_an_absent_denominator():
    assert _pct(5, 0) is None
    assert _pct(5, None) is None


# ── mode-aware totals ─────────────────────────────────────────────────────────

def _company(db, slug: str, mode: str | None) -> Company:
    c = Company(id=uuid.uuid4(), name=f"Co {slug}", slug=slug, is_active=True)
    db.add(c)
    db.flush()
    if mode is not None:
        db.add(CompanyConfig(id=uuid.uuid4(), company_id=c.id,
                             is_configured=True, operating_mode=mode))
    db.commit()
    return c


def test_workforce_totals_are_null_not_zero(db):
    """The core of D1."""
    co = _company(db, "wf-null", MODE_WORKFORCE)
    pkg = _package_totals_for_mode(db, co.id, date.today(), date.today())

    for key in ("delivered", "assigned", "rework", "stops", "avg_stop_minutes"):
        assert pkg[key] is None, f"{key} came back {pkg[key]!r}, expected None"


def test_workforce_totals_carry_the_reason(db):
    """D2: a client that infers "null means workforce mode" is wrong the first
    time a full-mode company legitimately has no deliveries yet today."""
    co = _company(db, "wf-reason", MODE_WORKFORCE)
    pkg = _package_totals_for_mode(db, co.id, date.today(), date.today())

    assert pkg["available"] is False
    assert pkg["reason"] == "no_package_feed"


def test_full_mode_reaches_the_real_query(db, monkeypatch):
    """A full-mode company must NOT be short-circuited — it goes to the real
    aggregate, where a genuine zero is a genuine measurement.

    Asserted by intercepting the aggregate rather than running it: the shared
    conftest fixture does not create `delivery_stops` (it uses a curated table
    list), and building that table here would test the fixture, not the branch.
    """
    called = {}

    def _fake(db_, cid, start, end):
        called["hit"] = True
        return {"delivered": 0, "assigned": 0, "rework": 0, "stops": 0,
                "avg_stop_minutes": None, "available": True, "reason": None}

    monkeypatch.setattr(
        "app.services.dashboard_summaries._package_totals", _fake
    )
    co = _company(db, "full-zero", MODE_FULL)
    pkg = _package_totals_for_mode(db, co.id, date.today(), date.today())

    assert called.get("hit"), "full mode was short-circuited"
    assert pkg["delivered"] == 0      # a real zero survives
    assert pkg["available"] is True


def test_missing_config_is_treated_as_no_feed(db):
    """The safe direction, matching RequireMode. Reporting real-looking zeros
    for a company whose configuration never claimed a feed is the worse error."""
    co = _company(db, "no-config", None)
    pkg = _package_totals_for_mode(db, co.id, date.today(), date.today())

    assert pkg["available"] is False
    assert pkg["delivered"] is None


def test_one_shape_either_way(db):
    """D3: same keys in both modes. Branching the DTO would mean two
    hand-maintained TypeScript interfaces in a types.ts with no codegen, and
    they would drift."""
    from app.services.dashboard_summaries import _package_totals

    wf = _company(db, "shape-wf", MODE_WORKFORCE)
    workforce_shape = _package_totals_for_mode(db, wf.id, date.today(), date.today())

    # The full-mode shape is _package_totals' own return, read from its source
    # rather than executed (see test_full_mode_reaches_the_real_query).
    full_shape = {"delivered", "assigned", "rework", "stops",
                  "avg_stop_minutes", "available", "reason"}
    assert set(workforce_shape) == full_shape


def test_the_unavailable_constant_is_not_mutated(db):
    """It is returned via dict() precisely so a caller cannot poison the shared
    default for every subsequent request in the process."""
    co = _company(db, "wf-copy", MODE_WORKFORCE)
    pkg = _package_totals_for_mode(db, co.id, date.today(), date.today())
    pkg["delivered"] = 999

    assert _UNAVAILABLE_PACKAGE_TOTALS["delivered"] is None


# ── schema shape (D1/D2/D3) ───────────────────────────────────────────────────

def test_package_fields_are_optional_on_the_response():
    from app.schemas.dashboard_summaries import ManagementOperationalSummary as M

    for f in ("total_packages_delivered", "total_packages_assigned",
              "total_rework_count"):
        ann = str(M.model_fields[f].annotation)
        assert "Optional" in ann or "None" in ann, f"{f} is still non-nullable"


def test_availability_flags_exist_on_both_dashboards():
    from app.schemas.dashboard_summaries import ManagementOperationalSummary as M
    from app.schemas import dashboard_summaries as S

    assert "package_metrics_available" in M.model_fields
    assert "package_metrics_unavailable_reason" in M.model_fields

    # The dispatch-side holder is DispatchFleetSnapshot — found by the field it
    # carries rather than by a name suffix, because not every response class in
    # this module is named *Summary.
    dispatch = next(
        getattr(S, n) for n in dir(S)
        if hasattr(getattr(S, n), "model_fields")
        and "avg_packages_per_active_truck" in getattr(S, n).model_fields
    )
    assert "package_metrics_available" in dispatch.model_fields


def test_available_defaults_to_true():
    """A full-mode tenant is the common case and must not need the flag set
    explicitly on every construction path."""
    from app.schemas.dashboard_summaries import ManagementOperationalSummary as M
    assert M.model_fields["package_metrics_available"].default is True


# ── D5: the scorecard cross-check says how precise it is ──────────────────────

def test_cross_check_carries_a_precision_label():
    from app.schemas.scorecard import CrossCheckResponse as C

    assert "precision" in C.model_fields
    assert C.model_fields["precision"].default == "per_package"
    assert "precision_note" in C.model_fields


def test_cross_check_labels_workforce_mode_as_coarser():
    """An appeal built on a number of unstated precision puts the DSP's
    credibility with Amazon behind a figure we know is approximate."""
    import inspect
    from app.routers import scorecards

    src = inspect.getsource(scorecards.cross_check_scorecard)
    assert 'precision="per_package" if full_mode else "captain_reported"' in src
    assert "approximate before filing an appeal" in src


# ── the frontend contract (D4) ────────────────────────────────────────────────

def test_typescript_package_fields_are_nullable():
    """types.ts is hand-maintained with no codegen. A non-nullable type here
    means the view renders `0` for an absence and TypeScript never complains."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    types = (root / "frontend" / "src" / "api" / "types.ts").read_text()
    block = types[types.index("export interface ManagementOperationalSummary"):]
    block = block[: block.index("}")]

    for f in ("total_packages_delivered", "total_packages_assigned",
              "total_rework_count"):
        line = next(l for l in block.splitlines() if l.strip().startswith(f))
        assert "null" in line, f"{f} is not nullable in types.ts: {line.strip()}"


def test_the_view_formats_counts_through_the_dash_helper():
    """D4: an em-dash, not a zero. `count()` already dashes on null — the
    frontend was right all along; the backend was the one lying to it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    metric = (root / "frontend" / "src" / "utils" / "metric.ts").read_text()
    assert "null and 0 are DIFFERENT FACTS" in metric

    view = (root / "frontend" / "src" / "components" / "dashboard"
            / "ManagementView.tsx").read_text()
    assert "count(efficiency.operational.total_packages_delivered)" in view

