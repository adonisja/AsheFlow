"""The setup window: ten sign-ups or thirty days, and roles granted in it are signed off (ADR-538).

Owner, 2026-10-18: a new company may add its existing, already-trained staff at
their real roles while 10 or fewer people have a sign-in account AND the
company is within 30 days of creation. Managers may then grant every role below
manager (field supervisor included) and set them via Edit; admins edit any role
any time; field supervisor is otherwise reached by promoting a driver. Every
grant that relies on the window carries the granter's sign-off.

These run the real handlers on sqlite with Cognito/Discord stubbed.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.models.company import Company
from app.routers import employees as E
from app.schemas.employee import BulkImportRow, EmployeeCreate, EmployeeUpdate, RoleTransitionRequest
from app.services import company_onboarding as CO
from tests.conftest import SEED_COMPANY_ID, make_employee


@pytest.fixture
def stubs():
    with patch.object(E, "_cognito_client", return_value=MagicMock()), \
         patch.object(E, "send_invite_email"), \
         patch.object(E, "write_notification"), \
         patch.object(E, "_fire_discord_dm"), \
         patch.object(E, "_fire_role_sync"):
        yield


def _age(db, days):
    db.get(Company, SEED_COMPANY_ID).created_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()


def _accounts(db, n):
    for i in range(n):
        e = make_employee(db, role="walker", name=f"Signed Up {i}")
        e.cognito_sub = str(uuid.uuid4())
    db.commit()


def _open(db):
    return CO.setup_window(db, SEED_COMPANY_ID)["open"]


# ── D1: the window ─────────────────────────────────────────────────────────

def test_a_new_company_with_no_sign_ups_is_open(db):
    assert _open(db)


def test_ten_sign_ups_is_open_and_eleven_closes_it(db):
    _accounts(db, 10)
    assert _open(db)
    _accounts(db, 1)
    assert not _open(db)


def test_a_deactivated_account_still_counts_so_it_never_reopens(db):
    _accounts(db, 11)
    assert not _open(db)
    for e in db.query(E.Employee).filter(E.Employee.cognito_sub.isnot(None)).limit(3):
        e.is_active = False
    db.commit()
    assert not _open(db)


def test_imported_rows_without_accounts_do_not_count(db):
    """The dsp-test trap: 132 active rows, 14 accounts."""
    for i in range(40):
        make_employee(db, role="walker", name=f"Seeded {i}").is_active = True
    db.commit()
    assert _open(db)


def test_day_30_is_open_and_day_31_is_closed(db):
    _age(db, 29)
    assert _open(db)
    _age(db, 31)
    assert not _open(db)


def test_an_unknown_company_is_closed(db):
    """Fail closed. The first draft read a missing company as OPEN."""
    assert CO.setup_window(db, uuid.uuid4())["open"] is False


def test_the_state_endpoint_reports_counts_and_days(db):
    mgr = make_employee(db, role="management", name="Mia")
    out = E.get_setup_window(caller=mgr, _={}, db=db)
    assert out["open"] is True and out["limit"] == 10 and 1 <= out["days_left"] <= 30


# ── D3 + D4: create, inside the window ─────────────────────────────────────

def _create(db, caller, role, reviewed=False, n=[0]):
    n[0] += 1
    return E.create_employee(EmployeeCreate(name=f"Person {n[0]}", email=f"x{n[0]}@example.com",
                                            role=role, roles_reviewed=reviewed), caller=caller, _={}, db=db)


@pytest.mark.parametrize("role", ["walker", "trainer", "driver", "captain", "field_supervisor"])
def test_in_the_window_a_manager_invites_experienced_staff_with_sign_off(db, stubs, role):
    mgr = make_employee(db, role="management", name="Max")
    assert _create(db, mgr, role, reviewed=True).role == role


@pytest.mark.parametrize("role", ["walker", "driver", "field_supervisor"])
def test_in_the_window_no_sign_off_is_refused(db, stubs, role):
    mgr = make_employee(db, role="management", name="Mo")
    with pytest.raises(HTTPException) as exc:
        _create(db, mgr, role, reviewed=False)
    assert exc.value.status_code == 400 and "sign off" in exc.value.detail


def test_hiring_roles_need_no_sign_off(db, stubs):
    """Only window-only grants are signed off; a trainee is a normal hire."""
    mgr = make_employee(db, role="management", name="Mel")
    assert _create(db, mgr, "trainee").role == "trainee"


def test_the_sign_off_is_audited(db, stubs):
    mgr = make_employee(db, role="management", name="Meg")
    emp = _create(db, mgr, "driver", reviewed=True)
    row = db.query(AuditLog).filter(AuditLog.target_id == emp.id, AuditLog.action_type == "employee.create").one()
    assert row.after_snapshot["window_signoff"] is True and row.after_snapshot["onboarding_window"] is True
    assert row.actor_id == mgr.id


@pytest.mark.parametrize("role", ["management", "admin"])
def test_even_in_the_window_a_manager_never_grants_manager_or_admin(db, stubs, role):
    mgr = make_employee(db, role="management", name="Mick")
    with pytest.raises(HTTPException) as exc:
        _create(db, mgr, role, reviewed=True)
    assert exc.value.status_code == 403


# ── outside the window ─────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["walker", "driver", "field_supervisor"])
def test_outside_the_window_earned_roles_are_refused_even_signed_off(db, stubs, role):
    _age(db, 40)
    mgr = make_employee(db, role="management", name="Mags")
    with pytest.raises(HTTPException) as exc:
        _create(db, mgr, role, reviewed=True)
    assert exc.value.status_code == 400 and "promoted" in exc.value.detail.lower() or "start as" in exc.value.detail


# ── bulk ───────────────────────────────────────────────────────────────────

def _bulk(db, caller, roles, reviewed):
    rows = [BulkImportRow(name=f"Row {i}", email=f"row{i}-{uuid.uuid4().hex[:6]}@example.com", role=r)
            for i, r in enumerate(roles)]
    return E.bulk_import_employees(rows, roles_reviewed=reviewed, caller=caller, _={}, db=db)


def test_bulk_without_sign_off_skips_window_rows_but_keeps_trainees(db, stubs):
    mgr = make_employee(db, role="management", name="Bea")
    out = _bulk(db, mgr, ["driver", "trainee"], reviewed=False)
    assert [r.status for r in out] == ["skipped", "created"]
    assert "sign off" in out[0].reason


def test_bulk_with_sign_off_creates_experienced_staff(db, stubs):
    mgr = make_employee(db, role="management", name="Bo")
    out = _bulk(db, mgr, ["walker", "driver", "field_supervisor", "trainee"], reviewed=True)
    assert all(r.status == "created" for r in out), [(r.status, r.reason) for r in out]


# ── edit ───────────────────────────────────────────────────────────────────

def _edit(db, caller, target, role):
    target.email, target.username = f"{target.id}@example.com", f"u.{str(target.id)[:6]}"
    db.commit()
    return E.update_employee(target.id, EmployeeUpdate(role=role), caller=caller,
                             current_user={"cognito_groups": [caller.role]}, db=db)


@pytest.mark.parametrize("role", ["walker", "driver", "captain", "field_supervisor"])
def test_in_the_window_a_manager_edits_to_any_role_below_manager(db, stubs, role):
    mgr, t = make_employee(db, role="management", name="Ed"), make_employee(db, role="trainee", name="Tee")
    assert _edit(db, mgr, t, role).role == role


def test_outside_the_window_a_manager_cannot_edit_to_field_supervisor(db, stubs):
    _age(db, 40)
    mgr, d = make_employee(db, role="management", name="Eve"), make_employee(db, role="driver", name="Dru")
    with pytest.raises(HTTPException) as exc:
        _edit(db, mgr, d, "field_supervisor")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["field_supervisor", "management", "walker"])
def test_an_admin_edits_any_role_outside_the_window(db, stubs, role):
    _age(db, 40)
    adm, t = make_employee(db, role="admin", name="Ada"), make_employee(db, role="driver", name="Dex")
    assert _edit(db, adm, t, role).role == role


# ── D2/D6: field supervisor by promotion ───────────────────────────────────

def test_a_driver_is_promoted_to_field_supervisor_outside_the_window(db, stubs):
    _age(db, 40)
    mgr, d = make_employee(db, role="management", name="Pam"), make_employee(db, role="driver", name="Dot")
    out = E.transition_employee_role(d.id, RoleTransitionRequest(new_role="field_supervisor"), caller=mgr,
                                     current_user={"cognito_groups": ["management"]}, db=db)
    assert out.role == "field_supervisor"


def test_a_field_supervisor_can_be_moved_back_to_driver(db, stubs):
    mgr, f = make_employee(db, role="management", name="Pat"), make_employee(db, role="field_supervisor", name="Fay")
    out = E.transition_employee_role(f.id, RoleTransitionRequest(new_role="driver"), caller=mgr,
                                     current_user={"cognito_groups": ["management"]}, db=db)
    assert out.role == "driver"


# ── D7: a row without a Discord ID is not a duplicate ─────────────────────

def test_rows_without_discord_ids_all_import(db, stubs):
    """`discord_id == None` compiles to IS NULL and matched every employee
    without one: only the first such row imported."""
    mgr = make_employee(db, role="management", name="Dee")
    out = _bulk(db, mgr, ["trainee", "trainee", "driver_trainee"], reviewed=False)
    assert [r.status for r in out] == ["created", "created", "created"], [(r.status, r.reason) for r in out]


def test_a_real_duplicate_discord_id_is_still_refused(db, stubs):
    mgr = make_employee(db, role="management", name="Dug")
    rows = [BulkImportRow(name="A", email="a-dup@example.com", role="trainee", discord_id="123456789012345678"),
            BulkImportRow(name="B", email="b-dup@example.com", role="trainee", discord_id="123456789012345678")]
    out = E.bulk_import_employees(rows, roles_reviewed=False, caller=mgr, _={}, db=db)
    assert [r.status for r in out] == ["created", "skipped"] and "Discord ID" in out[1].reason
