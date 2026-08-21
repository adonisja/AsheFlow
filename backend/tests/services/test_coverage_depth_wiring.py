"""Coverage depth reaches the management dashboard response (ADR-268).

`get_coverage_depth` had tests and a schema field for a full cycle while
`get_management_dashboard_summary` never called it, so the field serialized as
null forever and no test noticed — the service tests passed because they called
the service directly, and the dashboard tests passed because Optional[...] with
a None default is valid.

That is the gap these tests close: they assert the field is POPULATED by the
composed summary, not merely that it is well-typed.

THE PERIOD TRAP
Every other field on this dashboard honours the period selector (today / week /
month). Coverage depth deliberately does not — "who could I still call" has no
meaning averaged over last week, so it is always computed for today. A test
pins that, because the obvious "fix" is to make it follow the period like its
neighbours, which would silently turn it into a number nobody can act on.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import ARRAY as GA, MetaData, create_engine
from sqlalchemy.dialects.postgresql import ARRAY as PA, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# SQLite has no ARRAY/JSONB. Same shim the other ADR-268 service tests use —
# compile those types to JSON and hand-roll the (de)serialisation.
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

from app.models.assignment_change_request import AssignmentChangeRequest  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.delivery_stop import DeliveryStop  # noqa: E402
from app.models.field_ops import (  # noqa: E402
    Departure, VehicleInspection, WalkerRating,
)
from app.models.flex_timesheets import FlexTimesheet  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.models.package_manifest import PackageManifest  # noqa: E402
from app.models.rts_clearance import RTSReport  # noqa: E402
from app.models.shift_roll_call import ShiftRollCall  # noqa: E402
from app.models.walker_route import (  # noqa: E402
    MisroutedPackageFlag, Route, RouteParticipant,
)
from app.services.dashboard_summaries import (  # noqa: E402
    _company_today, get_management_dashboard_summary,
)
from app.services.outcome_signals import get_coverage_depth  # noqa: E402
from tests.conftest import (  # noqa: E402
    DISPATCH_TABLES, SEED_COMPANY_ID, make_assignment, make_employee,
    make_member, make_truck,
)


@pytest.fixture
def db():
    """The shared `db` fixture creates only the dispatch tables. The management
    dashboard reads well beyond those, so this fixture adds every table its
    query path touches — miss one and the failure is a bare "no such table"."""
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    meta = MetaData()
    for table in DISPATCH_TABLES + [
        Route.__table__, RouteParticipant.__table__, DeliveryStop.__table__,
        MisroutedPackageFlag.__table__, Incident.__table__,
        ShiftRollCall.__table__, WalkerRating.__table__, Departure.__table__,
        VehicleInspection.__table__, RTSReport.__table__,
        PackageManifest.__table__, FlexTimesheet.__table__,
        AssignmentChangeRequest.__table__,
    ]:
        table.to_metadata(meta)
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Company(id=SEED_COMPANY_ID, name="Test Co", slug="t",
                        is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


class TestCoverageDepthIsWiredIn:
    def test_management_summary_populates_coverage_depth(self, db):
        """The regression: field exists, service exists, nothing connects them."""
        make_employee(db, role="driver", name="Spare Driver")

        summary = get_management_dashboard_summary(db, SEED_COMPANY_ID, period="week")

        assert summary.crew.coverage_depth is not None, (
            "coverage_depth is null — the service is not being called"
        )
        assert summary.crew.coverage_depth.spare_drivers >= 1

    def test_it_reports_today_not_the_selected_period(self, db):
        """Coverage depth must be identical across period selections, because
        it is a today number. If it starts varying with `period`, someone has
        made it follow the dropdown and it no longer answers its question.

        THE SETUP IS THE TEST. The driver is rostered on a PAST date only, so
        "today" and "the start of the week/month" disagree about whether they
        are spare. Without that divergence every period returns the same count
        and the assertion holds no matter which date the service is handed —
        a test that cannot fail. Verified by planting `start` in place of
        `today`: with this setup the plant fails, without it, it passes.

        USE THE COMPANY CLOCK, NOT date.today(). The service computes its own
        "today" via `_company_today`, which is company-LOCAL. `date.today()` is
        the runner's UTC date, and the two disagree for every hour between UTC
        midnight and the company's midnight — a UTC-4 company is still on the
        previous date until 04:00 UTC. This test passed locally (afternoon,
        both clocks on the same date) and failed in CI at 01:46 UTC, where the
        fixture was built around Aug 13 while the service worked on Aug 12.
        Mixing the two clocks makes a test that fails only overnight.
        """
        driver = make_employee(db, role="driver", name="Period Test Driver")
        today = _company_today(db, SEED_COMPANY_ID)

        # A Monday-anchored week start is >= 1 day back whenever today is not
        # Monday; month start likewise. Roster them across that whole span so
        # any period-start date sees them ASSIGNED while today sees them SPARE.
        truck = make_truck(db, name="P1")
        span = (today - today.replace(day=1)).days
        for back in range(1, max(span, 7) + 1):
            asg = make_assignment(db, truck=truck,
                                  target_date=today - timedelta(days=back))
            make_member(db, assignment=asg, employee=driver, role="driver")

        today_view = get_coverage_depth(db, SEED_COMPANY_ID, today)
        assert today_view.spare_drivers >= 1, "fixture broken: not spare today"
        past_view = get_coverage_depth(db, SEED_COMPANY_ID,
                                       today - timedelta(days=1))
        assert past_view.assigned_drivers >= 1, "fixture broken: no divergence"

        per_period = {
            p: get_management_dashboard_summary(
                db, SEED_COMPANY_ID, period=p
            ).crew.coverage_depth
            for p in ("today", "week", "month")
        }
        spares = {p: c.spare_drivers for p, c in per_period.items()}
        assert len(set(spares.values())) == 1, (
            f"coverage depth changed with the period selector: {spares} — it is "
            "following the dropdown instead of reporting today"
        )
        assert spares["week"] == today_view.spare_drivers

    def test_composed_value_matches_the_service(self, db):
        """The dashboard must not re-derive the number its own way — a second
        implementation is a second set of exclusion rules to drift apart."""
        make_employee(db, role="captain", name="Parity Captain")

        composed = get_management_dashboard_summary(
            db, SEED_COMPANY_ID, period="week"
        ).crew.coverage_depth
        # Company clock, not date.today() — see the note in the period test.
        direct = get_coverage_depth(db, SEED_COMPANY_ID,
                                    _company_today(db, SEED_COMPANY_ID))

        assert composed.spare_drivers == direct.spare_drivers
        assert composed.spare_captains == direct.spare_captains
        assert composed.assigned_drivers == direct.assigned_drivers
        assert composed.at_capacity_risk == direct.at_capacity_risk