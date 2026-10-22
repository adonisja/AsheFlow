"""A company admin can issue a collection link (ADR-568).

The company-admin branch of POST /collection/tokens read caller.first_name and
caller.last_name, which Employee does not have, so every company admin's
request was a 500 from 2026-09-14 (e83728e8). The ADR-415 tests only read the
endpoint's signature; nothing ever ran the branch. These tests run it.
"""
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.audit_log import AuditLog
from app.models.collection import CollectionToken
from app.models.employee import Employee
from app.routers.collection import create_token
from app.schemas.collection import CollectionTokenCreate
from tests.conftest import SEED_COMPANY_ID, sqlite_mirror_with_defaults


@pytest.fixture(autouse=True)
def _setup(db):
    from app.api.ratelimit import limiter
    sqlite_mirror_with_defaults(CollectionToken.__table__).create(bind=db.get_bind(), checkfirst=True)
    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


def _request():
    return Request({"type": "http", "method": "POST", "path": "/collection/tokens", "headers": [],
                    "client": ("127.0.0.1", 1234), "query_string": b""})


def _emp(db, role):
    e = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=f"Pat {role.title()}", role=role,
                 is_active=True, username=f"pat.{role}", account_status="active")
    db.add(e); db.commit()
    return e


@pytest.mark.parametrize("role", ["admin", "management"])
def test_a_company_admin_issues_a_link_bound_to_their_company(db, role):
    caller = _emp(db, role)
    out = create_token(request=_request(), body=CollectionTokenCreate(label="Block survey"), db=db,
                       current_user={"cognito_groups": [role]}, caller=caller)
    tok = db.query(CollectionToken).filter(CollectionToken.id == out.id).one()
    assert tok.company_id == SEED_COMPANY_ID and tok.created_by == caller.id
    assert tok.created_by_name == caller.name, "the record keeps the employee's name of record"
    assert db.query(AuditLog).filter(AuditLog.action_type == "collection.token.create").count() == 1


def test_field_staff_still_cannot_issue_one(db):
    caller = _emp(db, "walker")
    with pytest.raises(HTTPException) as exc:
        create_token(request=_request(), body=CollectionTokenCreate(label="x"), db=db,
                     current_user={"cognito_groups": ["walker"]}, caller=caller)
    assert exc.value.status_code == 403
    assert db.query(CollectionToken).count() == 0
