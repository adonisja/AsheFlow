"""
Tests for the analytics router functions.

We test the query logic directly by calling the router functions with a real
SQLite session (bypassing the HTTP layer entirely). The role-checker dependency
`_` is satisfied by passing a plain dict — the functions don't use it.

HOW EACH FUNCTION WORKS:
1. get_dispatch_fill_rate  — groups AssignmentMember rows by date, splits by
   is_manual flag, returns summary + per-day breakdown.
2. get_trainer_load        — counts open TrainingRecord rows per trainer_id.
3. get_ban_override_freq   — counts Notification rows of type
   'ban_override_reassignment', bucketed into ISO weeks.
4. get_confirmation_times  — computes median/p90 of (confirmed_at - created_at)
   for DispatchConfirmation rows that have confirmed_at set.

WHAT WE'RE VERIFYING:
- Empty DB → sensible zero/empty returns (no crashes, no division by zero).
- Algo vs manual counts are computed correctly from is_manual flag.
- algo_pct rounds correctly.
- Trainer load counts only open (no submitted_at) records.
- Ban override buckets span the requested week range even when some weeks are zero.
- Confirmation times median and p90 maths are correct.
- By-role breakdown groups by employee.role correctly.
- Date range filtering is inclusive on both ends.

SQLITE NOTE:
DispatchConfirmation uses PostgreSQL UUID columns. We add it to a local targeted
MetaData for these tests (same pattern as DISPATCH_TABLES in conftest.py).
The CheckConstraints on DispatchConfirmation use SQLite-compatible SQL.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

SEED_COMPANY_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")

import pytest
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker

# Models needed for analytics
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.training import TrainingRecord
from app.models.notification import Notification
from app.models.dispatch_confirmation import DispatchConfirmation
from app.models.company import Company, CompanyConfig

# The four analytics functions under test
from app.routers.analytics import (
    get_dispatch_fill_rate,
    get_trainer_load,
    get_ban_override_freq,
    get_confirmation_times,
)

# ---------------------------------------------------------------------------
# Dedicated fixture — adds DispatchConfirmation to the schema
# ---------------------------------------------------------------------------

ANALYTICS_TABLES = [
    Company.__table__,
    CompanyConfig.__table__,
    Employee.__table__,
    Truck.__table__,
    TruckAssignment.__table__,
    AssignmentMember.__table__,
    TrainingRecord.__table__,
    Notification.__table__,
    DispatchConfirmation.__table__,
]


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    meta = MetaData()
    for table in ANALYTICS_TABLES:
        table.to_metadata(meta)
    meta.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add(Company(
        id=SEED_COMPANY_ID,
        name="Test Company",
        slug="test-company",
        is_active=True,
    ))
    session.flush()
    session.add(CompanyConfig(
        id=uuid.UUID("b0000000-0000-0000-0000-000000000001"),
        company_id=SEED_COMPANY_ID,
        is_configured=True,
        rating_window_hours=6,
        invite_expiry_days=7,
        graduation_assignments=5,
        debt_escalation_threshold=3,
        phase4_pass_score=90.0,
        underperforming_trainer_threshold=3,
        max_training_phase=4,
        dispatch_weight_driver=0.70,
        dispatch_weight_trainer=0.50,
        dispatch_weight_walker=0.30,
        dispatch_mutual_bonus=0.10,
        dispatch_tridirectional_bonus=0.20,
        dispatch_consecutive_penalty=0.05,
        dispatch_weight_cap=0.85,
        flag_threshold=1.0,
    ))
    session.commit()

    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_employee(db, role: str = "driver", name: str = "Test") -> Employee:
    emp = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=name, role=role, is_active=True,
                   discord_id=str(uuid.uuid4()))
    db.add(emp); db.commit(); db.refresh(emp)
    return emp


def make_assignment(db, truck_id, target_date: date) -> TruckAssignment:
    """Get or create a TruckAssignment for truck+date."""
    ta = db.query(TruckAssignment).filter(
        TruckAssignment.truck_id == truck_id,
        TruckAssignment.date == target_date,
    ).first()
    if ta is None:
        ta = TruckAssignment(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=truck_id, date=target_date)
        db.add(ta); db.commit(); db.refresh(ta)
    return ta


def make_member(db, assignment: TruckAssignment, employee: Employee,
                role: str = "driver", is_manual: bool = False) -> AssignmentMember:
    m = AssignmentMember(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        assignment_id=assignment.id,
        employee_id=employee.id,
        role=role,
        is_manual=is_manual,
    )
    db.add(m); db.commit(); db.refresh(m)
    return m


def make_truck(db, name: str = "Truck") -> Truck:
    t = Truck(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=name, is_active=True)
    db.add(t); db.commit(); db.refresh(t)
    return t


def make_open_training_record(db, trainee: Employee, trainer: Employee,
                               day: int = 1) -> TrainingRecord:
    """Create an open (not submitted) training record."""
    rec = TrainingRecord(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        trainee_id=trainee.id,
        trainer_id=trainer.id,
        current_day_number=day,
        record_date=date.today(),
        submitted_at=None,
    )
    db.add(rec); db.commit(); db.refresh(rec)
    return rec


def make_closed_training_record(db, trainee: Employee, trainer: Employee) -> TrainingRecord:
    """Create a closed (submitted) training record."""
    rec = TrainingRecord(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        trainee_id=trainee.id,
        trainer_id=trainer.id,
        current_day_number=2,
        record_date=date.today() - timedelta(days=1),
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(rec); db.commit(); db.refresh(rec)
    return rec


def make_override_notification(db, employee: Employee,
                                when: datetime = None) -> Notification:
    notif = Notification(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        employee_id=employee.id,
        type="ban_override_reassignment",
        message="Override fired",
        created_at=when or datetime.now(timezone.utc),
    )
    db.add(notif); db.commit(); db.refresh(notif)
    return notif


def make_confirmation(db, employee: Employee, dispatch_date: date,
                       status: str, response_minutes: float = None) -> DispatchConfirmation:
    """
    Create a DispatchConfirmation row.
    If response_minutes is given, set created_at and confirmed_at to produce
    exactly that many minutes of response time.
    """
    now = datetime.now(timezone.utc)
    created_at   = now - timedelta(minutes=response_minutes or 0)
    confirmed_at = now if response_minutes is not None else None

    conf = DispatchConfirmation(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        employee_id=employee.id,
        date=dispatch_date,
        status=status,
        created_at=created_at,
        confirmed_at=confirmed_at,
        source="discord_bot",
    )
    db.add(conf); db.commit(); db.refresh(conf)
    return conf


TODAY = date.today()


def make_admin_caller(db) -> Employee:
    """Return an admin employee scoped to SEED_COMPANY_ID for use as `caller`."""
    emp = Employee(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        name="Test Admin",
        role="admin",
        is_active=True,
        discord_id=str(uuid.uuid4()),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


# ---------------------------------------------------------------------------
# 1. Dispatch Fill Rate
# ---------------------------------------------------------------------------

class TestDispatchFillRate:
    """
    get_dispatch_fill_rate groups AssignmentMember rows by date and splits
    by is_manual. Rows with is_manual=False are algo; True are manual.
    """

    def test_empty_range_returns_zero_summary(self, db):
        """No assignments in range → summary all zeros, by_date empty."""
        result = get_dispatch_fill_rate(
            start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={}
        )
        assert result["summary"]["total_slots"]  == 0
        assert result["summary"]["algo_slots"]   == 0
        assert result["summary"]["manual_slots"] == 0
        assert result["summary"]["algo_pct"]     == 0.0
        assert result["by_date"] == []

    def test_algo_slots_counted_correctly(self, db):
        """
        ARRANGE: 2 algo members + 1 manual member on today.
        ASSERT: summary shows algo=2, manual=1, total=3, algo_pct=66.7.
        """
        truck  = make_truck(db)
        ta     = make_assignment(db, truck.id, TODAY)
        driver  = make_employee(db, role="driver",  name="D1")
        walker1 = make_employee(db, role="walker",  name="W1")
        walker2 = make_employee(db, role="walker",  name="W2")
        # ADR-322: the local make_member defaults role="driver", so this used
        # to put THREE drivers on one truck — which the partial unique index now
        # rejects, and which contradicted the employees' own roles anyway. The
        # counts under test are per-member and unchanged by naming them.
        make_member(db, ta, driver,  role="driver", is_manual=False)
        make_member(db, ta, walker1, role="walker", is_manual=False)
        make_member(db, ta, walker2, role="walker", is_manual=True)

        result = get_dispatch_fill_rate(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["summary"]["total_slots"]  == 3
        assert result["summary"]["algo_slots"]   == 2
        assert result["summary"]["manual_slots"] == 1
        assert result["summary"]["algo_pct"]     == 66.7

    def test_all_manual_gives_zero_algo_pct(self, db):
        truck = make_truck(db)
        ta    = make_assignment(db, truck.id, TODAY)
        d = make_employee(db, role="driver")
        make_member(db, ta, d, is_manual=True)

        result = get_dispatch_fill_rate(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["summary"]["algo_pct"]   == 0.0
        assert result["summary"]["algo_slots"] == 0

    def test_date_range_filters_out_of_range_rows(self, db):
        """
        ARRANGE: member on yesterday, query for today only.
        ASSERT: by_date is empty — yesterday is excluded.
        """
        truck     = make_truck(db)
        yesterday = TODAY - timedelta(days=1)
        ta        = make_assignment(db, truck.id, yesterday)
        d         = make_employee(db, role="driver")
        make_member(db, ta, d, is_manual=False)

        result = get_dispatch_fill_rate(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["by_date"] == []
        assert result["summary"]["total_slots"] == 0

    def test_by_date_includes_one_entry_per_day(self, db):
        """
        ARRANGE: members on day1 and day2 within range.
        ASSERT: by_date has exactly 2 entries.
        """
        truck = make_truck(db)
        day1  = TODAY - timedelta(days=2)
        day2  = TODAY - timedelta(days=1)
        d1 = make_employee(db, role="driver", name="D1")
        d2 = make_employee(db, role="driver", name="D2")
        make_member(db, make_assignment(db, truck.id, day1), d1, is_manual=False)
        make_member(db, make_assignment(db, truck.id, day2), d2, is_manual=False)

        result = get_dispatch_fill_rate(
            start_date=day1, end_date=day2, db=db, caller=make_admin_caller(db), _={}
        )

        assert len(result["by_date"]) == 2

    def test_date_range_inclusive_on_both_ends(self, db):
        """start_date and end_date rows must both be included."""
        truck = make_truck(db)
        start = TODAY - timedelta(days=3)
        end   = TODAY - timedelta(days=1)
        d_s = make_employee(db, role="driver", name="Start")
        d_e = make_employee(db, role="driver", name="End")
        make_member(db, make_assignment(db, truck.id, start), d_s)
        make_member(db, make_assignment(db, truck.id, end),   d_e)

        result = get_dispatch_fill_rate(start_date=start, end_date=end, db=db, caller=make_admin_caller(db), _={})

        dates_in_result = {row["date"] for row in result["by_date"]}
        assert str(start) in dates_in_result
        assert str(end)   in dates_in_result


# ---------------------------------------------------------------------------
# 2. Trainer Load
# ---------------------------------------------------------------------------

class TestTrainerLoad:
    """
    get_trainer_load returns one entry per trainer who has at least one open
    (submitted_at IS NULL) training record. Closed records are excluded.
    """

    def test_empty_db_returns_empty_list(self, db):
        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})
        assert result == []

    def test_trainer_with_one_open_record_counted(self, db):
        trainer = make_employee(db, role="trainer", name="Trainer A")
        trainee = make_employee(db, role="trainee", name="Trainee 1")
        make_open_training_record(db, trainee, trainer, day=1)

        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})

        assert len(result) == 1
        assert result[0]["trainer_name"]    == "Trainer A"
        assert result[0]["active_trainees"] == 1

    def test_closed_record_excluded(self, db):
        """
        ARRANGE: trainer has 1 open and 1 closed record.
        ASSERT: active_trainees == 1 (closed excluded).
        """
        trainer  = make_employee(db, role="trainer", name="Trainer")
        trainee1 = make_employee(db, role="trainee", name="Active Trainee")
        trainee2 = make_employee(db, role="trainee", name="Done Trainee")
        make_open_training_record(db, trainee1, trainer)
        make_closed_training_record(db, trainee2, trainer)

        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})

        assert len(result) == 1
        assert result[0]["active_trainees"] == 1

    def test_trainer_with_no_open_records_not_in_result(self, db):
        """A trainer whose only records are all closed should not appear."""
        trainer = make_employee(db, role="trainer", name="Done Trainer")
        trainee = make_employee(db, role="trainee", name="Graduated")
        make_closed_training_record(db, trainee, trainer)

        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})

        assert result == []

    def test_two_trainers_sorted_by_load_descending(self, db):
        """
        ARRANGE: trainer A has 2 open records, trainer B has 1.
        ASSERT: trainer A appears first (higher load first).
        """
        trainer_a = make_employee(db, role="trainer", name="Busy Trainer")
        trainer_b = make_employee(db, role="trainer", name="Light Trainer")
        t1 = make_employee(db, role="trainee", name="T1")
        t2 = make_employee(db, role="trainee", name="T2")
        t3 = make_employee(db, role="trainee", name="T3")
        make_open_training_record(db, t1, trainer_a)
        make_open_training_record(db, t2, trainer_a)
        make_open_training_record(db, t3, trainer_b)

        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})

        assert result[0]["trainer_name"] == "Busy Trainer"
        assert result[0]["active_trainees"] == 2
        assert result[1]["trainer_name"] == "Light Trainer"
        assert result[1]["active_trainees"] == 1

    def test_phase_breakdown_populated(self, db):
        """
        Phase breakdown dict must contain the correct counts per phase key.
        current_day_number values 1–4 map to phase keys "1"–"4".
        """
        trainer  = make_employee(db, role="trainer", name="Trainer")
        trainee1 = make_employee(db, role="trainee", name="Phase1 Trainee")
        trainee2 = make_employee(db, role="trainee", name="Phase2 Trainee")
        make_open_training_record(db, trainee1, trainer, day=1)
        make_open_training_record(db, trainee2, trainer, day=2)

        result = get_trainer_load(db=db, caller=make_admin_caller(db), _={})

        phases = result[0]["phases"]
        assert phases["1"] == 1
        assert phases["2"] == 1
        assert phases["3"] == 0
        assert phases["4"] == 0


# ---------------------------------------------------------------------------
# 3. Ban Override Frequency
# ---------------------------------------------------------------------------

class TestBanOverrideFreq:
    """
    get_ban_override_freq counts Notification rows of type
    'ban_override_reassignment' bucketed into ISO weeks.
    The result always covers exactly `weeks` week buckets, even if some are zero.
    """

    def test_no_overrides_returns_zero_total(self, db):
        result = get_ban_override_freq(weeks=4, db=db, caller=make_admin_caller(db), _={})
        assert result["total_overrides"] == 0
        assert result["weeks"] == 4

    def test_always_returns_correct_week_count(self, db):
        """by_week must have exactly `weeks` entries regardless of data."""
        for n in [4, 8, 12]:
            result = get_ban_override_freq(weeks=n, db=db, caller=make_admin_caller(db), _={})
            assert len(result["by_week"]) == n, f"Expected {n} week buckets, got {len(result['by_week'])}"

    def test_override_in_current_week_counted(self, db):
        """A notification created today must appear in the current week's bucket."""
        employee = make_employee(db)
        make_override_notification(db, employee, when=datetime.now(timezone.utc))

        result = get_ban_override_freq(weeks=4, db=db, caller=make_admin_caller(db), _={})

        assert result["total_overrides"] == 1

        # The last bucket is the current week — it should have count=1
        last_bucket = result["by_week"][-1]
        assert last_bucket["count"] == 1

    def test_override_outside_range_excluded(self, db):
        """A notification older than `weeks` weeks must not be counted."""
        employee = make_employee(db)
        old_time = datetime.now(timezone.utc) - timedelta(weeks=5)
        make_override_notification(db, employee, when=old_time)

        result = get_ban_override_freq(weeks=4, db=db, caller=make_admin_caller(db), _={})

        assert result["total_overrides"] == 0

    def test_other_notification_types_excluded(self, db):
        """Only 'ban_override_reassignment' type notifications count."""
        employee = make_employee(db)
        notif = Notification(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            employee_id=employee.id,
            type="trainee_graduated",
            message="Graduated",
            created_at=datetime.now(timezone.utc),
        )
        db.add(notif); db.commit()

        result = get_ban_override_freq(weeks=4, db=db, caller=make_admin_caller(db), _={})

        assert result["total_overrides"] == 0

    def test_multiple_overrides_summed(self, db):
        """3 overrides in the current week → total_overrides == 3."""
        emp = make_employee(db)
        now = datetime.now(timezone.utc)
        for _ in range(3):
            make_override_notification(db, emp, when=now)

        result = get_ban_override_freq(weeks=4, db=db, caller=make_admin_caller(db), _={})

        assert result["total_overrides"] == 3


# ---------------------------------------------------------------------------
# 4. Confirmation Response Time
# ---------------------------------------------------------------------------

class TestConfirmationTimes:
    """
    get_confirmation_times computes median and p90 of confirmed_at - created_at
    for DispatchConfirmation rows with confirmed_at set.
    Pending rows (no confirmed_at) are excluded.
    """

    def test_no_confirmations_returns_zero_overall(self, db):
        result = get_confirmation_times(
            start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={}
        )
        assert result["overall"]["total_responses"] == 0
        assert result["overall"]["median_minutes"]  == 0.0
        assert result["overall"]["p90_minutes"]     == 0.0
        assert result["by_role"] == []

    def test_pending_row_excluded(self, db):
        """A confirmation with status='pending' and no confirmed_at must not count."""
        emp = make_employee(db, role="driver")
        conf = DispatchConfirmation(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=emp.id, date=TODAY,
            status="pending", confirmed_at=None,
            created_at=datetime.now(timezone.utc), source="discord_bot",
        )
        db.add(conf); db.commit()

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["overall"]["total_responses"] == 0

    def test_single_confirmed_response_median_correct(self, db):
        """Single response of 30 minutes → median = 30."""
        emp = make_employee(db, role="driver")
        make_confirmation(db, emp, TODAY, status="confirmed", response_minutes=30)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["overall"]["total_responses"] == 1
        assert result["overall"]["median_minutes"]  == 30.0

    def test_median_of_three_values(self, db):
        """
        ARRANGE: response times of 10, 20, 60 minutes for three drivers.
        ASSERT: median == 20 (middle value of sorted list).
        """
        for minutes, name in [(10, "Fast"), (20, "Mid"), (60, "Slow")]:
            emp = make_employee(db, role="driver", name=name)
            make_confirmation(db, emp, TODAY, status="confirmed", response_minutes=minutes)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["overall"]["total_responses"] == 3
        assert result["overall"]["median_minutes"]  == 20.0

    def test_p90_value_computed(self, db):
        """
        ARRANGE: 10 responses with times 10..100 minutes.
        ASSERT: p90 is the 90th-percentile value (index 9 of sorted list = 100).
        """
        for i, minutes in enumerate(range(10, 110, 10)):  # 10,20,...,100
            emp = make_employee(db, role="driver", name=f"Driver {i}")
            make_confirmation(db, emp, TODAY, status="confirmed", response_minutes=minutes)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        # Sorted: [10,20,30,40,50,60,70,80,90,100]. idx = int(10 * 90/100) = 9 → 100
        assert result["overall"]["p90_minutes"] == 100.0

    def test_by_role_groups_correctly(self, db):
        """
        ARRANGE: 1 driver (10m) and 1 walker (40m).
        ASSERT: by_role has two entries, driver median=10, walker median=40.
        """
        driver = make_employee(db, role="driver", name="Driver")
        walker = make_employee(db, role="walker", name="Walker")
        make_confirmation(db, driver, TODAY, status="confirmed", response_minutes=10)
        make_confirmation(db, walker, TODAY, status="confirmed", response_minutes=40)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        by_role = {r["role"]: r for r in result["by_role"]}
        assert "driver" in by_role
        assert "walker" in by_role
        assert by_role["driver"]["median_minutes"] == 10.0
        assert by_role["walker"]["median_minutes"] == 40.0

    def test_date_range_filtering_excludes_out_of_range(self, db):
        """A confirmation for yesterday must not appear in a today-only query."""
        emp       = make_employee(db, role="driver")
        yesterday = TODAY - timedelta(days=1)
        make_confirmation(db, emp, yesterday, status="confirmed", response_minutes=15)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["overall"]["total_responses"] == 0

    def test_declined_response_included(self, db):
        """
        Declined confirmations with confirmed_at set count toward response time.
        A decline is still a response — the employee actively responded.
        """
        emp = make_employee(db, role="driver")
        make_confirmation(db, emp, TODAY, status="declined", response_minutes=25)

        result = get_confirmation_times(start_date=TODAY, end_date=TODAY, db=db, caller=make_admin_caller(db), _={})

        assert result["overall"]["total_responses"] == 1
        assert result["overall"]["median_minutes"]  == 25.0
