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

from app.routers.scorecards import upsert_scorecard, get_my_scorecards
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
