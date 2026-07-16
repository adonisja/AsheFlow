"""Scorecard upsert/validation (ADR-204 Phase B). scorecards.py is public.

Mock-DB tests of the create endpoint's validation branches and the self-scoped
read. Full DB round-trips are covered by the model + migration; here we pin the
branch logic that raises before commit.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from datetime import date

from app.routers.scorecards import (
    upsert_scorecard, get_my_scorecards, cross_check_scorecard,
    _iso_week_range, _num,
)
from app.schemas.scorecard import ScorecardCreate, ScorecardMetricIn


_CID = uuid.uuid4()
_ME = uuid.uuid4()
_EMP = uuid.uuid4()


def _caller(role="management", emp_id=_ME):
    c = MagicMock()
    c.id = emp_id
    c.company_id = _CID
    c.role = role
    c.name = "Mgr"
    return c


def _db(*, employee=None, existing=None):
    db = MagicMock()

    def _query(model):
        from app.models.employee import Employee
        from app.models.scorecard import Scorecard
        q = MagicMock()

        def _filter(*a, **k):
            f = MagicMock()
            f.filter.return_value = f
            f.order_by.return_value = f
            if model is Employee:
                f.first.return_value = employee
            elif model is Scorecard:
                f.first.return_value = existing
                f.all.return_value = []
            else:
                f.first.return_value = None
                f.all.return_value = []
            return f

        q.filter = _filter
        return q

    db.query = _query
    return db


def _body(**kw):
    base = dict(week="2026-W28", scope="individual", employee_id=_EMP,
                overall_standing="PLATINUM", metrics=[
                    ScorecardMetricIn(key="packages_delivered", label="Packages Delivered", value="203", sort_order=0),
                ])
    base.update(kw)
    return ScorecardCreate(**base)


def _run(db, caller, body):
    with patch("app.routers.scorecards.write_audit"):
        return upsert_scorecard(payload=body, caller=caller, _=None, db=db)


class TestUpsertValidation:
    def test_individual_requires_employee_id(self):
        with pytest.raises(HTTPException) as exc:
            _run(_db(), _caller(), _body(scope="individual", employee_id=None))
        assert exc.value.status_code == 400

    def test_company_must_not_name_employee(self):
        with pytest.raises(HTTPException) as exc:
            _run(_db(), _caller(), _body(scope="company", employee_id=_EMP))
        assert exc.value.status_code == 400

    def test_individual_unknown_employee_404(self):
        with pytest.raises(HTTPException) as exc:
            _run(_db(employee=None), _caller(), _body())
        assert exc.value.status_code == 404

    def test_creates_new_scorecard_with_metrics(self):
        emp = SimpleNamespace(id=_EMP, name="Ana", company_id=_CID)
        db = _db(employee=emp, existing=None)
        added = []
        db.add.side_effect = lambda o: added.append(o)
        out = _run(db, _caller(), _body())
        assert out["week"] == "2026-W28"
        assert out["employee_name"] == "Ana"
        assert len(added) == 1                       # the new Scorecard row
        assert len(added[0].metrics) == 1            # metric appended

    def test_company_scope_ok_without_employee(self):
        db = _db(existing=None)
        added = []
        db.add.side_effect = lambda o: added.append(o)
        out = _run(db, _caller(), _body(scope="company", employee_id=None))
        assert out["scope"] == "company"
        assert out["employee_id"] is None


class TestSelfScope:
    def test_me_queries_only_caller_own(self):
        db = _db()
        # get_my_scorecards returns [] here; the assertion is it doesn't raise and
        # is scoped to the caller (no employee_id param — uses caller.id).
        result = get_my_scorecards(caller=_caller(role="walker", emp_id=_ME), db=db)
        assert result == []


# ── Phase D: cross-check ────────────────────────────────────────────────────────

class TestCrossCheckHelpers:
    def test_iso_week_range(self):
        assert _iso_week_range("2026-W28") == (date(2026, 7, 6), date(2026, 7, 12))
        assert _iso_week_range("garbage") is None

    def test_num_extraction(self):
        assert _num("203") == 203.0
        assert _num("14492.7") == 14492.7
        assert _num("100.0%") == 100.0
        assert _num("14,492") == 14492.0
        assert _num("PLATINUM") is None


def _scorecard(metrics, scope="individual", employee_id=_EMP, week="2026-W28"):
    return SimpleNamespace(
        id=uuid.uuid4(), company_id=_CID, scope=scope, employee_id=employee_id, week=week,
        metrics=[SimpleNamespace(key=k, value=v) for k, v in metrics],
    )


def _xc_db(*, scorecard, delivered, rts, missing, evidence_rows=None):
    """Mock Session for cross_check: Scorecard.first()→scorecard; the three scalar
    aggregates in call order (delivered, rts, missing); rts evidence .all()."""
    db = MagicMock()
    scalars = [delivered, rts, missing]

    def _query(*models):
        from app.models.scorecard import Scorecard
        m = MagicMock()
        for attr in ("filter", "group_by", "order_by"):
            getattr(m, attr).return_value = m
        m.first.return_value = scorecard if models and models[0] is Scorecard else None
        m.scalar.side_effect = lambda: scalars.pop(0) if scalars else 0
        m.all.side_effect = lambda: (evidence_rows or [])
        return m

    db.query = _query
    return db


def _run_xc(db):
    from app.routers.scorecards import cross_check_scorecard as _xc
    return _xc(scorecard_id=uuid.uuid4(), caller=_caller(), _=None, db=db)


class TestCrossCheck:
    def test_delivered_matches_not_contestable(self):
        sc = _scorecard([("packages_delivered", "200"), ("delivery_completion_dpmo", "10000")])
        db = _xc_db(scorecard=sc, delivered=200, rts=2, missing=0)
        resp = _run_xc(db)
        pkg = next(i for i in resp.items if i.metric == "packages_delivered")
        assert pkg.amazon_value == 200 and pkg.our_value == 200
        assert pkg.contestable is False

    def test_delivered_mismatch_is_contestable(self):
        sc = _scorecard([("packages_delivered", "203")])
        db = _xc_db(scorecard=sc, delivered=150, rts=0, missing=0)   # 53 gap → contestable
        resp = _run_xc(db)
        pkg = next(i for i in resp.items if i.metric == "packages_delivered")
        assert pkg.contestable is True
        assert pkg.delta == 53.0

    def test_dpmo_higher_than_ours_is_contestable_with_evidence(self):
        # Amazon says 50000 DPMO; our record (5 rts of 100 attempted = 50000)…
        # push Amazon well above ours to trigger contestable.
        sc = _scorecard([("delivery_completion_dpmo", "90000")])
        db = _xc_db(scorecard=sc, delivered=95, rts=5, missing=0,   # ours = 5/100 = 50000
                    evidence_rows=[("no_safe_location", 3), ("access_issue", 2)])
        resp = _run_xc(db)
        dpmo = next(i for i in resp.items if i.metric == "delivery_completion_dpmo")
        assert dpmo.our_value == 50000.0
        assert dpmo.contestable is True                    # 90000 > 50000 * 1.25
        assert [(e.rts_type, e.count) for e in resp.rts_evidence] == \
            [("no_safe_location", 3), ("access_issue", 2)]

    def test_company_scorecard_rejected(self):
        sc = _scorecard([], scope="company", employee_id=None)
        db = _xc_db(scorecard=sc, delivered=0, rts=0, missing=0)
        with pytest.raises(HTTPException) as exc:
            _run_xc(db)
        assert exc.value.status_code == 400
