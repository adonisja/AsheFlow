"""Assignment history and difficulty-normalised RTS rate (ADR-268).

THE THING THIS EXISTS TO PROTECT
RTS rate is confounded by route difficulty. Measured on staging before the
service was written: 2.10% on easy routes, 5.11% standard, 10.81% heavy — a 5x
spread driven by the route, not the walker. Ranking people on raw rts_rate puts
whoever drew the hard routes at the bottom.

`rts_rate_vs_class` divides by the company rate for the SAME effort class, so
1.0 means "exactly typical for a route this hard". A real staging day: 4.97%
raw on a heavy route -> 0.46 vs_class, i.e. less than half the expected
returns, where the raw figure reads as merely average.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import ARRAY as GA, MetaData, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PA, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# Route and DeliveryStop use Postgres ARRAY/JSONB, which SQLite cannot compile —
# the very reason conftest builds a targeted table list instead of create_all.
# Shimmed HERE rather than in conftest: registering a global compiler override
# would change how every other suite renders those types.
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


# The compiler override handles DDL; these handle the VALUES. Without them a
# Python list reaches sqlite3 directly and raises "type 'list' is not
# supported". Same shim as tests/services/test_package_intake.py.
for _T in (GA, PA, JSONB):
    _T.bind_processor = _bind
    _T.result_processor = _result

from app.models.delivery_stop import DeliveryStop
from app.models.rts import RTSPackage
from app.models.walker_route import (
    MisroutedPackageFlag, Route, RouteParticipant,
)
from app.services.assignment_history import (
    ADDRESS_RETENTION_HOURS, _class_baselines, get_assignment_history,
)
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_truck,
)


from app.models.company import Company, CompanyConfig  # noqa: E402
from tests.conftest import DISPATCH_TABLES  # noqa: E402


@pytest.fixture
def db():
    """Like conftest's `db`, plus the three tables this feature joins through.

    Not added to DISPATCH_TABLES because their ARRAY/JSONB columns need the
    compiler shim above, and forcing that on every suite is a wider change than
    this feature warrants.
    """
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    meta = MetaData()
    for table in DISPATCH_TABLES + [
        Route.__table__, DeliveryStop.__table__, RTSPackage.__table__,
        # Route eager-loads these two; without them the SELECT joins to a
        # table SQLite has never heard of.
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


def _route(db, assignment, when, *, number=1, effort="standard"):
    r = Route(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_date=when,
        truck_assignment_id=assignment.id, route_number=number,
        status="completed", package_count=0, capacity_limit=50,
        effort_class=effort, block_keys=[], tote_ids=[], tba_numbers=[],
        normalised_addresses=[], stops=[],
    )
    db.add(r); db.commit()
    return r


def _stop(db, route, *, total, rts, effort="standard", seq=1, address=None):
    s = DeliveryStop(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        block_key="W_37_St_500", tba_numbers=[], status="completed",
        stop_sequence=seq, packages_total=total, packages_delivered=total - rts,
        rts_count=rts, missing_count=0, effort_class=effort,
        normalised_address=address,
    )
    db.add(s); db.commit()
    return s


def _rts(db, route, *, rts_type="no_access", address=None):
    r = RTSPackage(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
        truck_assignment_id=route.truck_assignment_id,
        tba_number=f"TBA{uuid.uuid4().hex[:10].upper()}",
        rts_type=rts_type, rts_explanation="seeded for test",
        is_reattemptable=True, normalised_address=address,
    )
    db.add(r); db.commit()
    return r


_bulk_n = [90]


def _bulk(db, when, *, effort, packages, rts, assignment):
    """Enough volume for a class to clear the baseline minimum.

    route_number increments because (truck_assignment_id, route_number) is
    unique — two baseline routes on one assignment collide otherwise.
    """
    _bulk_n[0] += 1
    route = _route(db, assignment, when, number=_bulk_n[0], effort=effort)
    _stop(db, route, total=packages, rts=rts, effort=effort, seq=_bulk_n[0])
    return route


class TestDifficultyNormalisation:
    def test_a_heavy_route_is_not_penalised_for_its_difficulty(self, db):
        """THE point of the feature. Two walkers with the SAME raw rate — one on
        easy routes, one on heavy — must not read as equal, because the heavy
        one is beating a much harder baseline."""
        when = date.today() - timedelta(days=5)
        emp = make_employee(db, role="walker", name="Heavy Hauler")
        truck = make_truck(db, name="T-AH1")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")

        # Company baselines: easy 2%, heavy 10%. Built on a SEPARATE truck
        # assignment — routes on the caller's own assignment would be counted
        # into their day and swamp the figure under test.
        other_truck = make_truck(db, name="T-AH1-base")
        other = make_assignment(db, other_truck, target_date=when)
        _bulk(db, when, effort="easy",  packages=1000, rts=20,  assignment=other)
        _bulk(db, when, effort="heavy", packages=1000, rts=100, assignment=other)

        # This person's day: 5% raw on a HEAVY route — half the heavy baseline.
        r = _route(db, a, when, number=1, effort="heavy")
        _stop(db, r, total=200, rts=10, effort="heavy")

        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        assert len(days) == 1, "the caller worked one truck that day"
        day = days[0]
        assert day.effort_class == "heavy"
        assert day.rts_rate == pytest.approx(10 / 200)          # raw 5%

        # THE assertion, pinned to an exact ratio.
        #
        # 0.55, not 0.50: the baseline is company-wide and INCLUDES this day's
        # own packages — (100+10)/(1000+200) = 9.17%, and 5% / 9.17% = 0.55.
        # Self-inclusion is correct (the company rate is the company rate) and
        # its effect shrinks as volume grows; pinning the real number documents
        # it instead of hiding it behind a tolerance.
        #
        # Deliberately an EQUALITY, not `< 1.0`. The looser form passes when the
        # normalisation is deleted entirely — 0.05 is also below 1.0 — which a
        # planted regression proved. A ratio test has to pin the ratio.
        assert day.rts_rate_vs_class == pytest.approx(0.55, abs=0.01)
        assert day.rts_rate_vs_class != pytest.approx(day.rts_rate), (
            "vs_class is the raw rate — the class baseline was not applied"
        )

    def test_baselines_are_computed_from_the_data(self, db):
        when = date.today() - timedelta(days=5)
        truck = make_truck(db, name="T-AH2")
        a = make_assignment(db, truck, target_date=when)
        _bulk(db, when, effort="easy",  packages=1000, rts=20,  assignment=a)
        _bulk(db, when, effort="heavy", packages=1000, rts=100, assignment=a)
        b = _class_baselines(db, SEED_COMPANY_ID)
        assert b["easy"] == pytest.approx(0.02)
        assert b["heavy"] == pytest.approx(0.10)

    def test_a_low_volume_class_is_not_used_as_a_denominator(self, db):
        """Dividing by a 12-package baseline produces ratios that swing on one
        return. Better to report no ratio than a meaningless one."""
        when = date.today() - timedelta(days=5)
        emp = make_employee(db, role="walker", name="Thin Data")
        truck = make_truck(db, name="T-AH3")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        r = _route(db, a, when, effort="heavy")
        _stop(db, r, total=12, rts=3, effort="heavy")

        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        day = days[0]
        assert day.rts_rate is not None            # raw rate is still honest
        assert day.rts_rate_vs_class is None       # but no ratio from 12 packages


class TestDayContents:
    def test_it_reports_the_slot_role_not_the_job_title(self, db):
        """A captain-titled employee riding as a walker worked a walker's day
        (ADR-256 D2)."""
        when = date.today() - timedelta(days=3)
        emp = make_employee(db, role="captain", name="Cap As Walker")
        truck = make_truck(db, name="T-AH4")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        assert days[0].slot_role == "walker"

    def test_the_crew_excludes_the_caller(self, db):
        when = date.today() - timedelta(days=3)
        me = make_employee(db, role="walker", name="Me Myself")
        them = make_employee(db, role="driver", name="Other Person")
        truck = make_truck(db, name="T-AH5")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, me, "walker")
        make_member(db, a, them, "driver")
        days = get_assignment_history(db, SEED_COMPANY_ID, me.id, when, when)
        names = [c["name"] for c in days[0].crew]
        assert "Other Person" in names
        assert "Me Myself" not in names

    def test_rts_details_carry_the_reason(self, db):
        when = date.today() - timedelta(days=3)
        emp = make_employee(db, role="walker", name="Rts Haver")
        truck = make_truck(db, name="T-AH6")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        r = _route(db, a, when)
        _stop(db, r, total=10, rts=1)
        _rts(db, r, rts_type="business_closed", address="505 WEST 37 STREET")

        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        detail = days[0].rts_details[0]
        assert detail.rts_type == "business_closed"
        assert detail.rts_explanation
        assert detail.normalised_address == "505 WEST 37 STREET"

    def test_days_are_newest_first(self, db):
        emp = make_employee(db, role="walker", name="Many Days")
        truck = make_truck(db, name="T-AH7")
        for n in (2, 5, 9):
            a = make_assignment(db, truck, target_date=date.today() - timedelta(days=n))
            make_member(db, a, emp, "walker")
        days = get_assignment_history(
            db, SEED_COMPANY_ID, emp.id, date.today() - timedelta(days=30), date.today())
        assert [d.route_date for d in days] == sorted(
            [d.route_date for d in days], reverse=True)


class TestAddressRetention:
    def test_recent_days_report_street_detail(self, db):
        """ADR-219 nulls addresses 48h after the route date, so a day inside the
        window still has them."""
        when = date.today()
        emp = make_employee(db, role="walker", name="Fresh Day")
        truck = make_truck(db, name="T-AH8")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        assert days[0].address_detail == "street"

    def test_old_days_report_block_detail(self, db):
        when = date.today() - timedelta(days=10)
        emp = make_employee(db, role="walker", name="Old Day")
        truck = make_truck(db, name="T-AH9")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        assert days[0].address_detail == "block"

    def test_detail_comes_from_the_window_not_from_finding_an_address(self, db):
        """A recent day with NO RTS must still report 'street' — otherwise the
        UI would claim addresses expired when the day simply went perfectly."""
        when = date.today()
        emp = make_employee(db, role="walker", name="Clean Day")
        truck = make_truck(db, name="T-AH10")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        r = _route(db, a, when)
        _stop(db, r, total=10, rts=0)          # zero RTS, so zero addresses
        days = get_assignment_history(db, SEED_COMPANY_ID, emp.id, when, when)
        assert days[0].rts_details == []
        assert days[0].address_detail == "street"

    def test_the_retention_constant_matches_adr_219(self):
        assert ADDRESS_RETENTION_HOURS == 48


class TestTenancy:
    def test_another_companys_days_are_never_returned(self, db):
        when = date.today() - timedelta(days=3)
        emp = make_employee(db, role="walker", name="Ours")
        truck = make_truck(db, name="T-AH11")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        days = get_assignment_history(db, uuid.uuid4(), emp.id, when, when)
        assert days == []

    def test_no_days_is_an_empty_list_not_an_error(self, db):
        emp = make_employee(db, role="walker", name="Never Worked")
        days = get_assignment_history(
            db, SEED_COMPANY_ID, emp.id, date.today() - timedelta(days=5), date.today())
        assert days == []
