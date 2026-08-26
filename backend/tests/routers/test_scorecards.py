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


def _xc_db(*, scorecard, delivered, rts, missing, evidence_rows=None,
           full_mode=True, carried_rows=None):
    """Mock Session for cross_check: Scorecard.first()→scorecard; the three scalar
    aggregates in call order (delivered, rts, missing); rts evidence .all().

    `full_mode` is now explicit (ADR-301). It used to be implied by
    CompanyConfig.first() returning None, which read as WORKFORCE — so these
    full-mode tests silently took the workforce branch the moment one existed.
    A mock that returns None for every model answers questions it was never
    asked, and the default it implies is the one nobody chose.
    """
    db = MagicMock()
    # Workforce mode never runs the DeliveryStop aggregate, so `delivered` must
    # not sit in the queue there — otherwise rts/missing shift by one and the
    # arithmetic is silently off by the delivered value.
    scalars = [delivered, rts, missing] if full_mode else [rts, missing]

    def _query(*models):
        from app.models.scorecard import Scorecard
        from app.models.company import CompanyConfig
        m = MagicMock()
        for attr in ("filter", "group_by", "order_by", "join"):
            getattr(m, attr).return_value = m
        if models and models[0] is Scorecard:
            m.first.return_value = scorecard
        elif models and models[0] is CompanyConfig:
            m.first.return_value = SimpleNamespace(
                operating_mode="full" if full_mode else "workforce")
        else:
            m.first.return_value = None
        m.scalar.side_effect = lambda: scalars.pop(0) if scalars else 0
        # Workforce mode reads (flex_package_count,) rows off the route join;
        # full mode's only .all() here is the RTS evidence.
        # Dispatch on the COLUMN being queried, not on mode: the route join
        # selects Route.flex_package_count, the evidence query selects
        # RTSPackage.rts_type. Guessing from mode made both look alike and the
        # 1-tuple carried rows were handed to the 2-tuple evidence unpack.
        _first = models[0] if models else None
        _is_carried = getattr(_first, "key", None) == "flex_package_count"
        m.all.side_effect = lambda: (
            (carried_rows or []) if _is_carried else (evidence_rows or [])
        )
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

    # ── ADR-301: the workforce branch, executed end-to-end ────────────────

    def test_workforce_uses_carried_minus_returned_not_deliverystop(self):
        """The inversion this ADR fixes. Before: delivered=0 -> delta=amazon,
        every scorecard contestable, and our_dpmo pinned at 1,000,000 so no
        completion appeal could ever fire."""
        sc = _scorecard([("packages_delivered", "300"),
                         ("delivery_completion_dpmo", "5000")])
        db = _xc_db(scorecard=sc, delivered=0, rts=3, missing=1,
                    full_mode=False, carried_rows=[(200,), (110,)])
        res = _run_xc(db)

        assert res.our_carried == 310
        assert res.our_delivered is None, "workforce mode has no delivery count"
        assert res.routes_unrecorded == 0

        pkg = next(i for i in res.items if i.metric == "packages_delivered")
        assert pkg.our_value == 306.0          # 310 carried - 3 rts - 1 missing
        assert pkg.contestable is False        # was True for every week

        dpmo = next(i for i in res.items if i.metric == "delivery_completion_dpmo")
        assert dpmo.our_value is not None and dpmo.our_value < 1_000_000

    def test_workforce_real_defect_gap_is_appealable(self):
        """The suppressed case: Amazon charging more defects than our record
        supports must now flag contestable."""
        sc = _scorecard([("packages_delivered", "300"),
                         ("delivery_completion_dpmo", "150000")])
        db = _xc_db(scorecard=sc, delivered=0, rts=30, missing=5,
                    full_mode=False, carried_rows=[(310,)])
        res = _run_xc(db)
        dpmo = next(i for i in res.items if i.metric == "delivery_completion_dpmo")
        assert dpmo.contestable is True

    def test_workforce_unrecorded_route_withholds_the_comparison(self):
        """D3 — NULL is not zero. An appeal built on a fabricated discrepancy
        costs more credibility than a missing comparison does."""
        sc = _scorecard([("packages_delivered", "300"),
                         ("delivery_completion_dpmo", "5000")])
        db = _xc_db(scorecard=sc, delivered=0, rts=3, missing=1,
                    full_mode=False, carried_rows=[(200,), (None,)])
        res = _run_xc(db)

        assert res.our_carried is None, "a partial sum understates what was carried"
        assert res.routes_unrecorded == 1
        for item in res.items:
            assert item.our_value is None
            assert item.contestable is False

    def test_company_scorecard_rejected(self):
        sc = _scorecard([], scope="company", employee_id=None)
        db = _xc_db(scorecard=sc, delivered=0, rts=0, missing=0)
        with pytest.raises(HTTPException) as exc:
            _run_xc(db)
        assert exc.value.status_code == 400


class TestUnplannedExcludedFromCrossCheck:
    """ADR-246: a field-added package must not enter our_delivered.

    It was never manifested to Amazon, so counting it inflates OUR number,
    makes Amazon's look too low, and manufactures a discrepancy against
    ourselves in an appeal we are the ones filing. The comparison is only
    meaningful across packages both sides know about.

    Asserted on the compiled SQL rather than through the mocked Session in
    _xc_db, which cannot see a filter at all — the bug this pins is a MISSING
    filter, so a mock that ignores filters would pass either way.
    """

    def test_delivered_query_filters_out_unplanned_stops(self):
        import inspect as _inspect
        from app.routers import scorecards as sc_mod

        src = _inspect.getsource(sc_mod.cross_check_scorecard)
        delivered_block = src.split("delivered = db.query(")[1].split(".scalar()")[0]
        assert "is_unplanned" in delivered_block, (
            "cross_check's delivered count no longer excludes unplanned stops — "
            "field-added packages (ADR-246) will inflate our_delivered and "
            "invert the appeal against us"
        )

    def test_the_flag_still_exists_on_the_model(self):
        """If is_unplanned is ever renamed, the filter above must move with it."""
        from app.models.delivery_stop import DeliveryStop
        assert "is_unplanned" in DeliveryStop.__table__.columns


class TestUnplannedPolicyDiffersByConsumer:
    """The two `packages_delivered` consumers must NOT be made consistent.

    cross_check compares against AMAZON'S manifest -> exclude unplanned, or we
    manufacture a discrepancy against ourselves.
    _package_totals measures OUR throughput -> include them, or we understate
    work a walker actually did.

    Pinned because "these two queries disagree" reads like a bug, and making
    them agree silently breaks whichever one gets changed.
    """

    def test_cross_check_excludes_unplanned(self):
        import inspect
        from app.routers import scorecards as sc
        block = inspect.getsource(sc.cross_check_scorecard).split("delivered = db.query(")[1]
        assert "is_unplanned" in block.split(".scalar()")[0]

    def test_dashboard_totals_include_unplanned(self):
        import inspect
        from app.services import dashboard_summaries as ds
        src = inspect.getsource(ds._package_totals)
        assert "is_unplanned" not in src, (
            "_package_totals now filters unplanned stops — if that was "
            "deliberate, update the docstring and this test; it measures our "
            "own throughput, where a found-and-delivered package counts"
        )
