"""Operational signals for the At-Risk list (ADR-268).

WHAT THIS PROTECTS
At-Risk was peer grade alone — a popularity-adjacent measure as the sole basis
for a page with consequences. These signals are outcomes the person controls,
but only usable once route difficulty is normalised out: measured 2.10% RTS on
easy routes against 10.81% on heavy, a 5x spread the walker does not choose.
Ranking on the raw rate flags whoever drew the hard work.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import ARRAY as GA, MetaData, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PA, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

for _T in (GA, PA, JSONB):
    compiles(_T, "sqlite")(lambda t, c, **kw: "JSON")


def _bind(self, dialect):
    import json
    return lambda v: None if v is None else json.dumps(v)


def _result(self, dialect, coltype=None):
    import json

    def p(v):
        if v is None or not isinstance(v, (str, bytes)):
            return v
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return p


for _T in (GA, PA, JSONB):
    _T.bind_processor = _bind
    _T.result_processor = _result

from app.models.company import Company  # noqa: E402
from app.models.delivery_stop import DeliveryStop  # noqa: E402
from app.models.rts import RTSPackage  # noqa: E402
from app.models.walker_route import (  # noqa: E402
    MisroutedPackageFlag, Route, RouteParticipant,
)
from app.services.outcome_signals import (  # noqa: E402
    AT_RISK_VS_CLASS, MIN_PACKAGES_FOR_SIGNAL, get_outcome_signals,
)
from tests.conftest import (  # noqa: E402
    DISPATCH_TABLES, SEED_COMPANY_ID, make_assignment, make_employee,
    make_member, make_truck,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    meta = MetaData()
    for table in DISPATCH_TABLES + [
        Route.__table__, DeliveryStop.__table__, RTSPackage.__table__,
        RouteParticipant.__table__, MisroutedPackageFlag.__table__,
    ]:
        table.to_metadata(meta)
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Company(id=SEED_COMPANY_ID, name="Test Co", slug="t", is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


_seq = [0]


def _route(db, assignment, when, *, effort="standard"):
    _seq[0] += 1
    r = Route(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_date=when,
        truck_assignment_id=assignment.id, route_number=_seq[0],
        status="completed", package_count=0, capacity_limit=50,
        effort_class=effort, block_keys=[], tote_ids=[], tba_numbers=[],
        normalised_addresses=[], stops=[],
    )
    db.add(r); db.commit()
    return r


def _stop(db, route, *, total, rts, effort, walker_id):
    _seq[0] += 1
    s = DeliveryStop(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key="W_37_St_500", tba_numbers=[], status="completed",
        stop_sequence=_seq[0], packages_total=total,
        packages_delivered=total - rts, rts_count=rts, missing_count=0,
        effort_class=effort, walker_id=walker_id,
    )
    db.add(s); db.commit()
    return s


def _baseline(db, a, when, *, effort, total, rts):
    """Company-wide volume so a class clears the baseline minimum."""
    filler = make_employee(db, role="walker", name=f"Filler {_seq[0]}")
    r = _route(db, a, when, effort=effort)
    _stop(db, r, total=total, rts=rts, effort=effort, walker_id=filler.id)


class TestDifficultyNormalisation:
    def test_a_heavy_worker_is_not_flagged_for_the_route(self, db):
        """THE point. Someone on heavy routes returns more packages for reasons
        they do not control; the raw rate would flag them, the ratio must not."""
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS1")
        a = make_assignment(db, truck, target_date=when)
        _baseline(db, a, when, effort="easy", total=1000, rts=20)    # 2%
        _baseline(db, a, when, effort="heavy", total=1000, rts=100)  # 10%

        emp = make_employee(db, role="walker", name="Heavy Worker")
        make_member(db, a, emp, "walker")
        r = _route(db, a, when, effort="heavy")
        _stop(db, r, total=200, rts=20, effort="heavy", walker_id=emp.id)

        sig = get_outcome_signals(db, SEED_COMPANY_ID)[str(emp.id)]
        assert sig.rts_rate == pytest.approx(0.10)   # raw 10% — alarming alone
        assert sig.rts_rate_vs_class is not None
        assert sig.rts_rate_vs_class < AT_RISK_VS_CLASS
        assert sig.is_at_risk is False, (
            "flagged for working heavy routes — the normalisation did not apply"
        )

    def test_an_easy_worker_with_the_same_raw_rate_IS_flagged(self, db):
        """Same 10% raw rate, easy routes. Against a 2% baseline that is 5x,
        and it should surface — this is the comparison the ratio exists for."""
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS2")
        a = make_assignment(db, truck, target_date=when)
        _baseline(db, a, when, effort="easy", total=1000, rts=20)
        _baseline(db, a, when, effort="heavy", total=1000, rts=100)

        emp = make_employee(db, role="walker", name="Easy Worker")
        make_member(db, a, emp, "walker")
        r = _route(db, a, when, effort="easy")
        _stop(db, r, total=200, rts=20, effort="easy", walker_id=emp.id)

        sig = get_outcome_signals(db, SEED_COMPANY_ID)[str(emp.id)]
        assert sig.rts_rate == pytest.approx(0.10)   # identical raw rate
        assert sig.rts_rate_vs_class >= AT_RISK_VS_CLASS
        assert sig.is_at_risk is True

    def test_identical_raw_rates_produce_opposite_verdicts(self, db):
        """The two tests above, stated as one claim: raw rate is not a verdict
        and difficulty is what decides."""
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS3")
        a = make_assignment(db, truck, target_date=when)
        _baseline(db, a, when, effort="easy", total=1000, rts=20)
        _baseline(db, a, when, effort="heavy", total=1000, rts=100)

        hard = make_employee(db, role="walker", name="Hard Routes")
        easy = make_employee(db, role="walker", name="Easy Routes")
        rh = _route(db, a, when, effort="heavy")
        re_ = _route(db, a, when, effort="easy")
        _stop(db, rh, total=200, rts=20, effort="heavy", walker_id=hard.id)
        _stop(db, re_, total=200, rts=20, effort="easy", walker_id=easy.id)

        sigs = get_outcome_signals(db, SEED_COMPANY_ID)
        h, e = sigs[str(hard.id)], sigs[str(easy.id)]
        assert h.rts_rate == e.rts_rate            # same raw number
        assert h.is_at_risk != e.is_at_risk        # opposite verdicts


class TestVolumeGate:
    def test_a_light_worker_is_never_flagged(self, db):
        """Flagging someone on 8 packages would be indefensible — one bad stop
        swings the rate completely."""
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS4")
        a = make_assignment(db, truck, target_date=when)
        _baseline(db, a, when, effort="easy", total=1000, rts=20)

        emp = make_employee(db, role="walker", name="Barely Worked")
        r = _route(db, a, when, effort="easy")
        _stop(db, r, total=8, rts=4, effort="easy", walker_id=emp.id)  # 50%!

        sig = get_outcome_signals(db, SEED_COMPANY_ID)[str(emp.id)]
        assert sig.rts_rate == pytest.approx(0.5)
        assert sig.has_enough_volume is False
        assert sig.is_at_risk is False, "flagged on 8 packages"

    def test_the_gate_threshold_is_what_it_claims(self, db):
        assert MIN_PACKAGES_FOR_SIGNAL == 100


class TestShape:
    def test_missing_packages_are_counted(self, db):
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS5")
        a = make_assignment(db, truck, target_date=when)
        emp = make_employee(db, role="walker", name="Has Missing")
        r = _route(db, a, when)
        s = _stop(db, r, total=50, rts=1, effort="standard", walker_id=emp.id)
        s.missing_count = 3
        db.commit()
        sig = get_outcome_signals(db, SEED_COMPANY_ID)[str(emp.id)]
        assert sig.missing_count == 3

    def test_unattributed_stops_belong_to_nobody(self, db):
        """A stop with no walker_id must not be silently credited to anyone."""
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS6")
        a = make_assignment(db, truck, target_date=when)
        r = _route(db, a, when)
        _stop(db, r, total=50, rts=5, effort="standard", walker_id=None)
        assert get_outcome_signals(db, SEED_COMPANY_ID) == {}

    def test_another_company_is_never_included(self, db):
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-OS7")
        a = make_assignment(db, truck, target_date=when)
        emp = make_employee(db, role="walker", name="Ours")
        r = _route(db, a, when)
        _stop(db, r, total=50, rts=1, effort="standard", walker_id=emp.id)
        assert get_outcome_signals(db, uuid.uuid4()) == {}
