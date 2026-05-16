"""
conftest.py — shared test fixtures for the entire test suite.

pytest automatically loads this file before running any tests. Fixtures
defined here are available to every test file without needing to import them.

KEY CONCEPTS:
- We use SQLite in-memory (:memory:) instead of the real PostgreSQL container.
  SQLAlchemy's ORM works identically with both — the service code doesn't know
  or care which database it's talking to.
- Each test gets a completely fresh database via the `db` fixture. Nothing
  leaks between tests.
- Helper functions (make_employee, make_truck, etc.) let individual tests
  create exactly the rows they need with minimal boilerplate.
"""

import uuid
from datetime import date, datetime, timezone

SEED_COMPANY_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# We import only the models the dispatch services use.
# We deliberately do NOT import models that use PostgreSQL-specific column
# types like JSONB (VehicleInspection) — SQLite can't create those tables.
# Instead of Base.metadata.create_all (all tables), we create a targeted
# MetaData from only the tables we need.
from sqlalchemy import MetaData
from app.models.base import Base
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.employee_relationship import EmployeeRelationship
from app.models.employee_off_day import EmployeeOffDay
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.training import TrainingCurriculum, TrainingRecord, TrainingTask
from app.models.notification import Notification
from app.models.time_off_request import TimeOffRequest
from app.models.company import Company, CompanyConfig
from app.models.shift_session import ShiftSession

# Collect only the Table objects for models we actually need in tests.
# Any model imported above registers its Table in Base.metadata.
# We build a targeted MetaData containing only those tables.
#
# Why not Base.metadata.create_all? Some models (VehicleInspection) use
# PostgreSQL-specific JSONB columns that SQLite cannot compile. This targeted
# list gives SQLite exactly the schema the dispatch services touch, nothing more.
DISPATCH_TABLES = [
    Company.__table__,
    Employee.__table__,
    Truck.__table__,
    TruckAssignment.__table__,
    AssignmentMember.__table__,
    EmployeeRelationship.__table__,
    EmployeeOffDay.__table__,
    TrainerContinuationRequest.__table__,
    TrainingCurriculum.__table__,
    TrainingRecord.__table__,
    TrainingTask.__table__,
    Notification.__table__,
    TimeOffRequest.__table__,
    CompanyConfig.__table__,
    ShiftSession.__table__,
]


# ---------------------------------------------------------------------------
# Database fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """
    Yield a fresh SQLite in-memory database session for one test.

    HOW IT WORKS:
    1. create_engine(':memory:') — creates a database that lives only in RAM.
       It disappears when the connection closes. No files, no cleanup needed.
    2. connect_args={'check_same_thread': False} — SQLite's default is to
       refuse multi-thread access. We disable that check because SQLAlchemy's
       session management is safe even though pytest may use threads.
    3. Base.metadata.create_all(engine) — runs CREATE TABLE for every model
       that inherits from Base. This gives us the full schema.
    4. 'yield session' — the test runs here. After it finishes (pass or fail),
       execution resumes after yield for cleanup.
    5. session.close() + engine.dispose() — tears down the connection and
       frees the in-memory database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Only create the tables the dispatch services touch.
    # Base.metadata.create_all would also try to create VehicleInspection
    # which uses PostgreSQL's JSONB type — SQLite can't compile that.
    meta = MetaData()
    for table in DISPATCH_TABLES:
        table.to_metadata(meta)
    meta.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed Company + fully-configured CompanyConfig so get_company_config
    # doesn't raise in tests. All required fields set to platform defaults.
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

    yield session  # <-- test runs here

    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Row-builder helpers
# ---------------------------------------------------------------------------
# These are plain functions (not fixtures) — call them inside tests to insert
# exactly the rows you need. Keeping defaults minimal means each test only
# specifies what's relevant to what it's testing.

def make_employee(db, role: str = "driver", name: str = "Test Employee") -> Employee:
    """Insert and return an active Employee with a fresh UUID."""
    emp = Employee(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        name=name,
        role=role,
        is_active=True,
        discord_id=str(uuid.uuid4()),  # unique per employee
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def make_truck(db, name: str = "Truck A") -> Truck:
    """Insert and return a Truck with a fresh UUID."""
    truck = Truck(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        name=name,
        is_active=True,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)
    return truck


def make_assignment(db, truck: Truck, target_date: date = None) -> TruckAssignment:
    """Insert and return a TruckAssignment for a truck on a given date."""
    ta = TruckAssignment(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        truck_id=truck.id,
        date=target_date or date.today(),
    )
    db.add(ta)
    db.commit()
    db.refresh(ta)
    return ta


def make_member(db, assignment: TruckAssignment, employee: Employee, role: str) -> AssignmentMember:
    """Link an employee to a TruckAssignment as a specific role."""
    member = AssignmentMember(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        assignment_id=assignment.id,
        employee_id=employee.id,
        role=role,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def make_relationship(db, employee: Employee, target: Employee, rel_type: str) -> EmployeeRelationship:
    """Insert a fav or ban relationship between two employees."""
    rel = EmployeeRelationship(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        employee_id=employee.id,
        target_employee_id=target.id,
        relationship_type=rel_type,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


def make_off_day(db, employee: Employee, day_of_week: str, status: str = "approved") -> EmployeeOffDay:
    """Insert a recurring off-day for an employee."""
    off = EmployeeOffDay(
        id=uuid.uuid4(),
        company_id=employee.company_id,
        employee_id=employee.id,
        day_of_week=day_of_week,
        status=status,
    )
    db.add(off)
    db.commit()
    db.refresh(off)
    return off


def make_time_off_request(db, employee: Employee, target_date: date, status: str = "approved") -> TimeOffRequest:
    """Insert an approved PTO request for an employee on a specific date."""
    tor = TimeOffRequest(
        id=uuid.uuid4(),
        company_id=employee.company_id,
        employee_id=employee.id,
        date=target_date,
        status=status,
    )
    db.add(tor)
    db.commit()
    db.refresh(tor)
    return tor


def make_curriculum(db, day_number: int, topic_title: str, is_mandatory: bool = True,
                    category: str = "app_setup", record_type: str = "coverage") -> TrainingCurriculum:
    """Insert a curriculum item for a given phase (day_number)."""
    item = TrainingCurriculum(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        day_number=day_number,
        topic_title=topic_title,
        description=f"Description for {topic_title}",
        is_mandatory=is_mandatory,
        category=category,
        record_type=record_type,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def make_training_record(db, trainee: Employee, trainer: Employee, record_date: date,
                         phase: int = 1, phase_closed: bool = False) -> TrainingRecord:
    """Insert a TrainingRecord for a trainee on a given date."""
    rec = TrainingRecord(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        trainee_id=trainee.id,
        trainer_id=trainer.id,
        record_date=record_date,
        current_day_number=phase,
        phase_closed=phase_closed,
        extended=False,
        is_locked=False,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def make_shift_session(db, driver: Employee, current_gate: int = 1,
                       completed_at=None) -> ShiftSession:
    """Insert a ShiftSession for a driver."""
    session = ShiftSession(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        driver_id=driver.id,
        current_gate=current_gate,
        completed_at=completed_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
