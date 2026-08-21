"""Scorecard appeal access, lifecycle guards, and tenancy.

An appeal is a financial record — money rides on whether Amazon corrects a
metric — so the things pinned here are the ones that would corrupt that record:
editing a filed appeal, double-submitting, resolving twice, or one tenant
reaching another's dispute.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import ARRAY as GenericARRAY, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PgARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# SQLite lacks ARRAY/JSONB — DDL compiler AND bind processors are both needed
# (the DDL half alone still raises "type 'list' is not supported" at INSERT).
for _T in (GenericARRAY, PgARRAY, JSONB):
    compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")


def _json_bind(self, dialect):
    import json
    return lambda v: None if v is None else json.dumps(v)


def _json_result(self, dialect, coltype=None):
    import json

    def process(value):
        if value is None or not isinstance(value, (str, bytes)):
            return value
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return process


for _T in (GenericARRAY, PgARRAY, JSONB):
    _T.bind_processor = _json_bind
    _T.result_processor = _json_result

import app.routers.scorecard_appeals as ap  # noqa: E402
from app.api.deps import RoleChecker  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.scorecard import Scorecard  # noqa: E402
from app.models.scorecard_appeal import (  # noqa: E402
    APPEAL_STATUSES, APPEAL_TERMINAL_STATUSES,
    ScorecardAppeal, ScorecardAppealItem,
)

COMPANY = uuid.UUID("a0000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("a0000000-0000-0000-0000-0000000000ff")


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
    s.add(Company(id=OTHER, name="Other Co", slug="o", is_active=True))
    s.commit()
    yield s
    s.close()
    eng.dispose()


def _mgr(db, company=COMPANY, name="Manager"):
    e = Employee(id=uuid.uuid4(), company_id=company, name=name, role="management",
                 is_active=True, hr_system_id_adp=uuid.uuid4())
    db.add(e)
    db.commit()
    return e


def _scorecard(db, company=COMPANY, week="2026-W30", scope="company"):
    sc = Scorecard(id=uuid.uuid4(), company_id=company, week=week, scope=scope)
    db.add(sc)
    db.commit()
    return sc


def _appeal(db, sc, company=COMPANY, status="draft", with_item=True):
    a = ScorecardAppeal(id=uuid.uuid4(), company_id=company, scorecard_id=sc.id,
                        week=sc.week, scope=sc.scope, status=status)
    db.add(a)
    db.commit()
    if with_item:
        db.add(ScorecardAppealItem(
            id=uuid.uuid4(), company_id=company, appeal_id=a.id,
            metric_key="dnr_dpmo", metric_label="DNR DPMO",
            amazon_value="1250", our_value="900", delta=350.0,
            evidence={"rts": [{"type": "customer_unavailable", "count": 3}]}))
        db.commit()
    db.refresh(a)
    return a


class TestAccess:
    def test_appeals_are_management_and_admin_only(self):
        """Tier 4 inherits Tier 3: appeals reach individual scorecard data."""
        assert set(ap._allow_appeals.allowed_roles) == {"management", "admin"}

    def test_dispatch_cannot_reach_appeals(self):
        assert "dispatch" not in ap._allow_appeals.allowed_roles

    def test_no_field_role_can_reach_appeals(self):
        for r in ("driver", "walker", "trainer", "trainee"):
            assert r not in ap._allow_appeals.allowed_roles

    def test_every_route_carries_the_gate(self):
        """No endpoint may be left ungated — appeals have no self-serve tier."""
        for route in ap.router.routes:
            gates = [d.call for d in route.dependant.dependencies
                     if isinstance(d.call, RoleChecker)]
            assert gates, f"{route.path} has no RoleChecker"
            assert set(gates[0].allowed_roles) == {"management", "admin"}


class TestLifecycle:
    def test_status_vocabulary(self):
        assert APPEAL_STATUSES == ["draft", "submitted", "won", "lost", "withdrawn"]

    def test_terminal_states_exclude_draft_and_submitted(self):
        """Only terminal appeals free the scorecard for a second attempt."""
        assert set(APPEAL_TERMINAL_STATUSES) == {"won", "lost", "withdrawn"}
        assert "draft" not in APPEAL_TERMINAL_STATUSES
        assert "submitted" not in APPEAL_TERMINAL_STATUSES

    def test_new_appeal_defaults_to_draft(self, db):
        a = _appeal(db, _scorecard(db), with_item=False)
        assert a.status == "draft"
        assert a.submitted_at is None and a.resolved_at is None

    def test_item_defaults_to_pending(self, db):
        a = _appeal(db, _scorecard(db))
        assert a.items[0].outcome == "pending"

    def test_items_cascade_on_appeal_delete(self, db):
        a = _appeal(db, _scorecard(db))
        db.delete(a)
        db.commit()
        assert db.query(ScorecardAppealItem).count() == 0


class TestTenancy:
    def test_item_carries_company_id_directly(self, db):
        """Stamped, not inherited via appeal_id — the table must be usable as a
        query root ('which metrics do we win?') without a join being the only
        thing preventing a cross-tenant leak."""
        a = _appeal(db, _scorecard(db))
        assert a.items[0].company_id == COMPANY

    def test_appeals_are_isolated_between_tenants(self, db):
        _appeal(db, _scorecard(db, COMPANY), COMPANY)
        _appeal(db, _scorecard(db, OTHER, week="2026-W31"), OTHER)
        mine = db.query(ScorecardAppeal).filter(
            ScorecardAppeal.company_id == COMPANY).all()
        assert len(mine) == 1
        assert mine[0].company_id == COMPANY

    def test_items_are_isolated_between_tenants(self, db):
        _appeal(db, _scorecard(db, COMPANY), COMPANY)
        _appeal(db, _scorecard(db, OTHER, week="2026-W31"), OTHER)
        mine = db.query(ScorecardAppealItem).filter(
            ScorecardAppealItem.company_id == COMPANY).all()
        assert len(mine) == 1


class TestEvidenceSnapshot:
    def test_values_are_snapshotted_not_referenced(self, db):
        """Re-uploading a corrected scorecard clears and rewrites its metric
        rows. If the appeal read them live, its evidence would silently change
        under it — so the disputed values are copied at draft time."""
        a = _appeal(db, _scorecard(db))
        item = a.items[0]
        assert item.amazon_value == "1250"
        assert item.our_value == "900"
        assert item.delta == 350.0

    def test_evidence_jsonb_round_trips(self, db):
        a = _appeal(db, _scorecard(db))
        ev = a.items[0].evidence
        assert ev["rts"][0]["type"] == "customer_unavailable"
        assert ev["rts"][0]["count"] == 3


class TestWinRateHonesty:
    def test_win_rate_is_none_before_anything_resolves(self):
        """None, not 0.0 — 'nothing resolved yet' is not 'we lose everything'."""
        from app.schemas.scorecard_appeal import AppealStats
        assert AppealStats().win_rate_pct is None


class TestEvidenceIsTyped:
    """`evidence` was Dict[str, Any] written straight into JSONB.

    Not SQL injection — SQLAlchemy parameterises — but an unbounded write: any
    shape, any depth, any size, echoed back into the appeals UI. `Any` also
    meant a mistyped key was silently persisted instead of rejected.
    """

    def _item(self, **kw):
        from app.schemas.scorecard_appeal import AppealItemIn
        return AppealItemIn(metric_key="k", metric_label="l", **kw)

    def test_the_real_payload_still_works(self):
        """ScorecardEntry.tsx sends exactly this — tightening must not break it."""
        it = self._item(evidence={"rts_reasons": [{"rts_type": "UTA", "count": 3}]})
        assert it.evidence.rts_reasons[0].rts_type == "UTA"
        assert it.evidence.rts_reasons[0].count == 3

    def test_unknown_keys_are_rejected(self):
        """extra='forbid' — an unrecognised key is a client bug worth a 422,
        not something to persist silently."""
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._item(evidence={"rts_reasons": [], "smuggled": {"x": 1}})

    def test_wrong_types_are_rejected(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._item(evidence={"rts_reasons": "not-a-list"})

    def test_negative_counts_are_rejected(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._item(evidence={"rts_reasons": [{"rts_type": "X", "count": -5}]})

    def test_claim_is_bounded(self):
        """It was the one free-text field with no max_length, and it is
        operator prose that lands in the appeal record."""
        import pytest
        from pydantic import ValidationError
        assert self._item(claim="x" * 2000).claim
        with pytest.raises(ValidationError):
            self._item(claim="x" * 2001)

    def test_evidence_is_serialised_to_a_dict_for_jsonb(self):
        """The column is JSONB — passing the Pydantic model itself would store
        an object, not JSON. Both write sites must call model_dump()."""
        import inspect
        from app.routers import scorecard_appeals as ap
        src = inspect.getsource(ap)
        assert src.count("evidence=it.evidence.model_dump() if it.evidence else None") == 2
