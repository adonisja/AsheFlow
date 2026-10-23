"""ADR-577: platform_support reaches the platform READ endpoints through the app.

ADR-343's tests called get_platform_staff directly, and it accepted support.
But companies.router is mounted with `_configured`, and require_configured
returned early only for super_admin: a support caller (no Employee row, by
design) got 403 "No employee record found" before get_platform_staff ran.
So these tests go through the mounted app, the way a request does.
"""
import uuid

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
from app.models.platform_session import PlatformSessionStamp
from app.services import mfa_status
from tests.conftest import sqlite_mirror_with_defaults


def _caller(groups, sub="platform-sub-1", username="support.person"):
    return {"id": sub, "username": username, "cognito_groups": groups, "auth_time": 1}


@pytest.fixture
def db():
    # TestClient serves the request on another thread, and the shared fixture's
    # in-memory SQLite gives each thread its own (empty) database. StaticPool
    # keeps one connection, so the request sees what the test wrote.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    for model in (Company, CompanyConfig, Employee, PlatformSessionStamp):
        sqlite_mirror_with_defaults(model.__table__).create(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    # Enrolled, so the MFA gate is not what this test measures.
    monkeypatch.setattr(mfa_status, "is_enrolled", lambda *a, **k: True)
    app.dependency_overrides[get_db] = lambda: db
    yield lambda caller: (app.dependency_overrides.__setitem__(D.get_current_user, lambda: caller),
                          TestClient(app))[1]
    app.dependency_overrides.clear()


@pytest.mark.parametrize("groups", [["platform_support"], ["super_admin"]])
def test_platform_staff_can_list_companies(client, groups):
    r = client(_caller(groups)).get("/api/v1/admin/companies/")
    assert r.status_code == 200, r.text


def test_support_still_cannot_write(client):
    r = client(_caller(["platform_support"])).post("/api/v1/admin/companies/", json={})
    assert r.status_code == 403, r.text


def test_an_employee_is_still_refused_the_platform_reads(client, db):
    company = Company(id=uuid.uuid4(), name="Tenant", slug="tenant")
    db.add(company)
    db.add(CompanyConfig(company_id=company.id, is_configured=True))
    db.add(Employee(id=uuid.uuid4(), company_id=company.id, name="An Admin", username="an.admin",
                    cognito_sub="admin-sub", role="admin", is_active=True))
    db.commit()
    r = client(_caller(["admin"], sub="admin-sub", username="an.admin")).get("/api/v1/admin/companies/")
    assert r.status_code == 403, r.text


def test_role_checker_resolves_by_sub_and_username_never_email(db):
    """RoleChecker used to fall back to EMAIL (ADR-560 removed that everywhere
    else). Unreachable while require_configured refused every tenant-less caller;
    reachable once support passes it: a support account sharing an admin's
    email would have been role-checked AS that admin."""
    from fastapi import HTTPException
    company = Company(id=uuid.uuid4(), name="Tenant", slug="tenant")
    db.add(company)
    db.add(Employee(id=uuid.uuid4(), company_id=company.id, name="An Admin", username="an.admin",
                    email="shared@example.test", cognito_sub="admin-sub", role="admin", is_active=True))
    db.commit()
    stranger = {"id": "other-sub", "username": "someone.else", "email": "shared@example.test",
                "cognito_groups": ["platform_support"]}
    with pytest.raises(HTTPException) as e:
        D.RoleChecker(["admin"])(user=stranger, db=db)
    assert e.value.status_code == 403
    # The real admin, by sub, still passes.
    owner = {"id": "admin-sub", "username": "an.admin", "cognito_groups": ["admin"]}
    D.RoleChecker(["admin"])(user=owner, db=db)
