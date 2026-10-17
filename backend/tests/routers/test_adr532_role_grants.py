"""Who may grant a role is one rule, enforced on every path (ADR-532).

Owner, 2026-10-17: admins invite any hiring role; managers invite trainees,
driver trainees and dispatchers; nobody else invites. Measured before the fix,
calling the real handlers with a manager as the caller:

    edit driver -> admin          ACCEPTED, Cognito add_to_group ['admin']
    bulk row role=admin           ACCEPTED -> created
    create admin, onboarding      ACCEPTED (manager check was `and not onboarding`)

These EXECUTE the handlers against the sqlite test DB with Cognito stubbed.
"""
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import employees as E
from app.schemas.employee import BulkImportRow, EmployeeCreate, EmployeeUpdate
from tests.conftest import make_employee

ROOT = pathlib.Path(__file__).resolve().parents[3]
ASSETS = ROOT / "frontend" / "src" / "pages" / "Assets.tsx"

ADMIN_GRANTS = {"trainee", "driver_trainee", "field_supervisor", "dispatch", "management", "admin"}
MANAGER_GRANTS = {"trainee", "driver_trainee", "dispatch"}


def _established(db):
    """Past the ADR-285 onboarding window: active field staff exist."""
    for i in range(2):
        w = make_employee(db, role="walker", name=f"Walker {i}")
        w.is_active = True
    db.commit()


def _caller(db, role):
    return make_employee(db, role=role, name=f"{role.title()} Caller")


@pytest.fixture
def stubs():
    with patch.object(E, "_cognito_client", return_value=MagicMock()) as cog, \
         patch.object(E, "send_invite_email", MagicMock(), create=True):
        yield cog


def _create(db, caller, role, n=[0]):
    n[0] += 1
    return E.create_employee(
        EmployeeCreate(name=f"New Person {n[0]}", email=f"p{n[0]}@example.com", role=role),
        caller=caller, _={}, db=db)


# ── the table, exactly ─────────────────────────────────────────────────────

def test_the_table_is_the_owners():
    assert set(E.ROLE_GRANTS["admin"]) == ADMIN_GRANTS
    assert set(E.ROLE_GRANTS["management"]) == MANAGER_GRANTS
    assert set(E.ROLE_GRANTS) == {"admin", "management"}, "only two roles grant at all"


# ── create ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", sorted(MANAGER_GRANTS))
def test_manager_creates_their_roles(db, stubs, role):
    _established(db)
    assert _create(db, _caller(db, "management"), role).role == role


@pytest.mark.parametrize("role", ["management", "admin", "field_supervisor"])
def test_manager_cannot_create_above_their_level(db, stubs, role):
    _established(db)
    with pytest.raises(HTTPException) as exc:
        _create(db, _caller(db, "management"), role)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["management", "admin"])
def test_manager_cannot_create_an_admin_during_onboarding_either(db, stubs, role):
    """THE onboarding hole: the old check ended `and not onboarding`."""
    assert E.is_onboarding(db, _caller(db, "management").company_id)
    mgr = db.query(E.Employee).filter(E.Employee.role == "management").first()
    with pytest.raises(HTTPException) as exc:
        _create(db, mgr, role)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", sorted(ADMIN_GRANTS))
def test_admin_creates_every_hiring_role(db, stubs, role):
    _established(db)
    assert _create(db, _caller(db, "admin"), role).role == role


@pytest.mark.parametrize("role", ["walker", "trainer", "driver", "captain"])
def test_earned_roles_are_refused_to_admins_too(db, stubs, role):
    """Owner kept the earned-role rule for everyone (ADR-264/256)."""
    _established(db)
    with pytest.raises(HTTPException) as exc:
        _create(db, _caller(db, "admin"), role)
    assert exc.value.status_code == 400


def test_onboarding_still_admits_earned_roles():
    """ADR-285's migration path survives -- for both callers."""
    for caller in ("admin", "management"):
        assert E._grant_refusal(caller, "driver", onboarding=True) is None


@pytest.mark.parametrize("caller", ["dispatch", "driver", "walker", "trainer", "field_supervisor"])
def test_no_other_role_grants_anything(caller):
    """The route gate is the first line (RoleChecker); this is the second."""
    for role in ADMIN_GRANTS:
        assert E._grant_refusal(caller, role, onboarding=False) is not None


# ── bulk import ────────────────────────────────────────────────────────────

def test_manager_bulk_row_for_an_admin_is_skipped_with_a_reason(db, stubs):
    _established(db)
    out = E.bulk_import_employees(
        [BulkImportRow(name="Eve Escalate", email="eve@example.com", role="admin"),
         BulkImportRow(name="Tia Trainee", email="tia@example.com", role="trainee")],
        caller=_caller(db, "management"), _={}, db=db)
    assert [r.status for r in out] == ["skipped", "created"], "one bad row must not sink the rest"
    assert "trainees, driver trainees and dispatchers" in out[0].reason


# ── edit ───────────────────────────────────────────────────────────────────

def _edit(db, caller, target, new_role):
    target.email, target.username = f"{target.id}@example.com", f"user.{str(target.id)[:6]}"
    db.commit()
    return E.update_employee(target.id, EmployeeUpdate(role=new_role), caller=caller,
                             current_user={"cognito_groups": [caller.role]}, db=db)


@pytest.mark.parametrize("new_role", ["admin", "management", "field_supervisor"])
def test_manager_cannot_edit_someone_into_a_protected_role(db, stubs, new_role):
    """THE edit escalation: driver -> admin was accepted and synced to Cognito."""
    mgr, drv = _caller(db, "management"), make_employee(db, role="driver", name="Dan Driver")
    with pytest.raises(HTTPException) as exc:
        _edit(db, mgr, drv, new_role)
    assert exc.value.status_code == 403
    stubs.return_value.admin_add_user_to_group.assert_not_called()
    db.refresh(drv)
    assert drv.role == "driver"


def test_manager_can_still_correct_a_field_role_on_edit(db, stubs):
    """ADR-532 D3: edit is where a role is corrected; not silently tightened."""
    mgr, emp = _caller(db, "management"), make_employee(db, role="trainee", name="Tom Trainee")
    assert _edit(db, mgr, emp, "dispatch").role == "dispatch"


def test_admin_can_edit_anyone_into_any_role(db, stubs):
    adm, emp = _caller(db, "admin"), make_employee(db, role="driver", name="Dee Driver")
    assert _edit(db, adm, emp, "management").role == "management"


def test_an_edit_that_keeps_the_role_is_not_a_grant(db, stubs):
    """Editing a phone number must not trip the grant check."""
    assert E._edit_grant_refusal("management", "walker") is None


# ── the web mirrors the table ──────────────────────────────────────────────

def _ts_list(name):
    m = re.search(rf"const {name} = \[([^\]]*)\]", ASSETS.read_text())
    assert m, f"{name} not found in Assets.tsx"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_web_invite_lists_equal_the_server_table():
    """Hand-maintained mirror; a drift offers a role the server refuses (it
    offered `driver`, as the default, for a month)."""
    assert _ts_list("CREATABLE_ROLES") == set(E.ROLE_GRANTS["admin"])
    assert _ts_list("MANAGEMENT_CREATABLE_ROLES") == set(E.ROLE_GRANTS["management"])
    assert _ts_list("MANAGEMENT_NEVER_GRANTS") == set(E._MANAGEMENT_NEVER_GRANTS)
