"""ADR-578: an endpoint that serves two kinds of caller is called as each.

ADR-568's collection links 500'd for every company admin for five weeks
because only the endpoint's signature was tested. These two endpoints have the
same shape: one branch for a caller with an Employee row, one for a platform
account without one. Each branch is called here through the mounted app, with a
real Employee row (a MagicMock has every attribute, so it hides the
AttributeError this exists to catch).
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps as D
from app.database import get_db
from app.main import app
from app.models.company import Company, CompanyConfig
from app.models.employee import Employee
from app.models.feedback import Feedback
from app.models.notification import Notification
from app.models.platform_alert import PlatformAlert
from app.models.platform_session import PlatformSessionStamp
from app.services import device_fleet, mfa_status
from tests.conftest import sqlite_mirror_with_defaults

TABLES = (Company, CompanyConfig, Employee, PlatformSessionStamp, Feedback, Notification, PlatformAlert)


@pytest.fixture
def db():
    # StaticPool: TestClient serves on another thread, and a plain in-memory
    # SQLite gives each thread its own empty database (ADR-577).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in TABLES:
        sqlite_mirror_with_defaults(model.__table__).create(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def tenant(db):
    company = Company(id=uuid.uuid4(), name="Tenant", slug="tenant")
    db.add(company)
    db.add(CompanyConfig(company_id=company.id, is_configured=True))
    admin = Employee(id=uuid.uuid4(), company_id=company.id, name="Ada Admin", username="ada.admin",
                     cognito_sub="admin-sub", role="admin", is_active=True)
    walker = Employee(id=uuid.uuid4(), company_id=company.id, name="Wes Walker", username="wes.walker",
                      cognito_sub="walker-sub", role="walker", is_active=True)
    db.add_all([admin, walker])
    db.commit()
    return company, admin, walker


@pytest.fixture
def call(db, monkeypatch):
    state = {"enrolled": True}
    monkeypatch.setattr(mfa_status, "is_enrolled", lambda *a, **k: state["enrolled"])
    monkeypatch.setattr(mfa_status, "read_setup_window", lambda *a, **k: (None, None))
    monkeypatch.setattr(device_fleet, "enforce_cap", lambda *a, **k: 0)
    app.dependency_overrides[get_db] = lambda: db

    def _call(method, path, caller, **kw):
        app.dependency_overrides[D.get_current_user] = lambda: caller
        return TestClient(app).request(method, path, **kw)
    _call.state = state
    yield _call
    app.dependency_overrides.clear()


def _user(sub, username, groups):
    return {"id": sub, "username": username, "cognito_groups": groups, "auth_time": 1}


class TestFeedback:
    BODY = {"type": "bug", "message": "The map does not load"}

    def test_an_employee_submits_and_their_company_admins_are_told(self, call, db, tenant):
        company, admin, walker = tenant
        r = call("POST", "/api/v1/feedback/", _user("walker-sub", "wes.walker", ["walker"]), json=self.BODY)
        assert r.status_code == 201, r.text
        fb = db.query(Feedback).one()
        assert fb.employee_id == walker.id and fb.company_id == company.id
        notes = db.query(Notification).all()
        assert [n.employee_id for n in notes] == [admin.id], "fan-out goes to the company's admins only"
        assert all(n.company_id == company.id for n in notes)
        assert db.query(PlatformAlert).count() == 0

    @pytest.mark.parametrize("groups", [["super_admin"], ["platform_support"]])
    def test_a_platform_account_submits_and_it_becomes_a_platform_alert(self, call, db, tenant, groups):
        r = call("POST", "/api/v1/feedback/", _user("platform-sub", "plat.person", groups), json=self.BODY)
        assert r.status_code == 201, r.text
        fb = db.query(Feedback).one()
        assert fb.employee_id is None and fb.company_id is None
        alert = db.query(PlatformAlert).one()
        assert alert.company_id is None and alert.alert_type == "feedback_submitted"
        assert db.query(Notification).count() == 0, "a tenant-less submission notifies no tenant"


class TestMyMfaStatus:
    def test_an_unenrolled_employee_gets_a_grace_clock_stamped_once(self, call, db, tenant):
        _, _, walker = tenant
        call.state["enrolled"] = False
        me = _user("walker-sub", "wes.walker", ["walker"])
        r = call("GET", "/api/v1/employees/me/mfa-status", me)
        assert r.status_code == 200, r.text
        assert r.json()["enrolled"] is False
        db.refresh(walker)
        first = walker.mfa_grace_started_at
        assert first is not None, "the first call opens the grace window"
        r2 = call("GET", "/api/v1/employees/me/mfa-status", me)
        assert r2.status_code == 200, r2.text
        db.refresh(walker)
        assert walker.mfa_grace_started_at == first, "a later call must not extend the window"

    def test_an_enrolled_employee_has_no_clock(self, call, db, tenant):
        _, _, walker = tenant
        r = call("GET", "/api/v1/employees/me/mfa-status", _user("walker-sub", "wes.walker", ["walker"]))
        assert r.status_code == 200, r.text
        assert r.json()["enrolled"] is True
        db.refresh(walker)
        assert walker.mfa_grace_started_at is None

    def test_a_platform_account_without_a_row_is_answered_from_its_group(self, call, db, tenant):
        r = call("GET", "/api/v1/employees/me/mfa-status", _user("platform-sub", "plat.person", ["platform_support"]))
        assert r.status_code == 200, r.text
        assert r.json()["tier"] == "privileged"
