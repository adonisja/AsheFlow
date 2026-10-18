"""Training can't be skipped by editing a role, and driver promotion exists (ADR-537).

Owner: training "cannot be skipped as it's an Amazon requirement"; Edit may set
earned roles for admins only; an incomplete driver promotion warns but is allowed,
management+admin only ("not a dispatcher concern").

Found while checking: RoleTransitionRequest.new_role was Literal[walker, trainer,
captain] (2026-08-08) while ROLE_TRANSITIONS gained driver_trainee -> driver
(2026-08-22) -- so no client could promote a driver, and the only route was the
Edit dropdown, which skipped training. These run the real handlers on sqlite.
"""
import inspect
import pathlib
import re
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.routers import employees as E
from app.schemas.employee import EmployeeUpdate, RoleTransitionRequest
from app.services import driver_promotion as DP
from tests.conftest import make_employee

ROOT = pathlib.Path(__file__).resolve().parents[3]
ASSETS = ROOT / "frontend" / "src" / "pages" / "Assets.tsx"


@pytest.fixture
def stubs():
    """Every outbound side effect of a role change, by its REAL name.

    The first version patched `send_role_change_dm` with create=True. No such
    name exists, so create=True silently made a new attribute, the real
    `_fire_discord_dm` ran, queued a Celery task, and in CI (no Redis) each
    successful promotion test failed with `Error 111 connecting to
    localhost:6379` after ~20 s of retries. Locally Redis was up, so it passed.
    No create=True: a wrong name must fail loudly."""
    with patch.object(E, "_cognito_client", return_value=MagicMock()), \
         patch.object(E, "write_notification"), \
         patch.object(E, "_fire_discord_dm"), \
         patch.object(E, "_fire_role_sync"):
        yield


def _edit(db, caller, target, new_role):
    target.email, target.username = f"{target.id}@example.com", f"u.{str(target.id)[:6]}"
    db.commit()
    return E.update_employee(target.id, EmployeeUpdate(role=new_role), caller=caller,
                             current_user={"cognito_groups": [caller.role]}, db=db)


# ── D1: Edit ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("earned", ["walker", "trainer", "driver", "captain"])
def test_a_manager_cannot_edit_a_trainee_into_an_earned_role(db, stubs, earned):
    mgr, t = make_employee(db, role="management", name="Mia Manager"), make_employee(db, role="trainee", name="Tia")
    with pytest.raises(HTTPException) as exc:
        _edit(db, mgr, t, earned)
    assert exc.value.status_code == 403 and "Only admins" in exc.value.detail
    db.refresh(t); assert t.role == "trainee"


def test_an_admin_can_still_correct_a_role_via_edit(db, stubs):
    adm, t = make_employee(db, role="admin", name="Ada Admin"), make_employee(db, role="trainee", name="Tom")
    assert _edit(db, adm, t, "walker").role == "walker"


def test_a_manager_editing_a_walkers_other_fields_is_not_a_grant(db, stubs):
    """The role isn't changing, so no grant check runs."""
    mgr, w = make_employee(db, role="management", name="Mo"), make_employee(db, role="walker", name="Wes")
    w.email, w.username = "wes@example.com", "wes.w"; db.commit()
    out = E.update_employee(w.id, EmployeeUpdate(role="walker"), caller=mgr,
                            current_user={"cognito_groups": ["management"]}, db=db)
    assert out.role == "walker"


def test_a_manager_can_still_move_between_hiring_roles(db, stubs):
    mgr, t = make_employee(db, role="management", name="Max"), make_employee(db, role="trainee", name="Ty")
    assert _edit(db, mgr, t, "driver_trainee").role == "driver_trainee"


# ── D2: driver promotion exists ────────────────────────────────────────────

def test_the_request_schema_accepts_driver():
    """THE bug: every driver promotion failed validation."""
    assert RoleTransitionRequest(new_role="driver").new_role == "driver"
    with pytest.raises(ValidationError):
        RoleTransitionRequest(new_role="admin")


def test_the_transition_route_stays_management_and_admin():
    """Not a dispatcher concern (owner)."""
    src = inspect.getsource(E.transition_employee_role)
    assert 'RoleChecker(["management", "admin"])' in src


# ── D3/D4: remaining phases warn; confirming overrides and is recorded ────

def _close_phases(db, trainee, phases):
    from app.models.training import TrainingRecord
    for p in phases:
        db.add(TrainingRecord(company_id=trainee.company_id, trainee_id=trainee.id,
                              record_date=date(2026, 10, p), current_day_number=p, phase_closed=True))
    db.commit()


def _promote(db, caller, trainee, confirm=False):
    return E.transition_employee_role(trainee.id, RoleTransitionRequest(new_role="driver", confirm_incomplete=confirm),
                                      caller=caller, current_user={"cognito_groups": [caller.role]}, db=db)


@pytest.fixture
def five_phases():
    cfg = MagicMock(); cfg.driver_training_days = 5
    with patch.object(DP, "get_company_config", return_value=cfg):
        yield


def test_remaining_phases_uses_the_observation_phase_definition(db, five_phases):
    t = make_employee(db, role="driver_trainee", name="Dee")
    _close_phases(db, t, [1, 2, 3])
    assert DP.driver_phases_remaining(db, t) == [4, 5]
    _close_phases(db, t, [5])                      # observation closed → finished
    assert DP.driver_phases_remaining(db, t) == []


def test_incomplete_promotion_is_refused_with_the_phases(db, stubs, five_phases):
    mgr, t = make_employee(db, role="management", name="Meg"), make_employee(db, role="driver_trainee", name="Dan")
    _close_phases(db, t, [1, 2])
    with pytest.raises(HTTPException) as exc:
        _promote(db, mgr, t)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "phases_incomplete" and exc.value.detail["remaining_phases"] == [3, 4, 5]
    db.refresh(t); assert t.role == "driver_trainee"


def test_confirmed_incomplete_promotion_goes_ahead_and_is_audited(db, stubs, five_phases):
    adm, t = make_employee(db, role="admin", name="Abe"), make_employee(db, role="driver_trainee", name="Dot")
    _close_phases(db, t, [1])
    assert _promote(db, adm, t, confirm=True).role == "driver"
    row = db.query(AuditLog).filter(AuditLog.target_id == t.id).order_by(AuditLog.created_at.desc()).first()
    assert row.after_snapshot["incomplete_override"] is True
    assert row.after_snapshot["remaining_phases"] == [2, 3, 4, 5]


def test_a_complete_trainee_promotes_without_confirmation(db, stubs, five_phases):
    mgr, t = make_employee(db, role="management", name="Mel"), make_employee(db, role="driver_trainee", name="Del")
    _close_phases(db, t, [1, 2, 3, 4, 5])
    out = _promote(db, mgr, t)
    assert out.role == "driver"
    row = db.query(AuditLog).filter(AuditLog.target_id == t.id).order_by(AuditLog.created_at.desc()).first()
    assert "incomplete_override" not in (row.after_snapshot or {})


# ── D5 and web parity ──────────────────────────────────────────────────────

def test_the_awaiting_promotion_warning_names_who_can_act():
    msg = DP.promotion_warning({"employee_name": "X", "verdict": "passed", "employee_id": "1"})["message"]
    assert "Management or an admin" in msg


def _ts(name):
    m = re.search(rf"const {name}[^=]*= (\{{[^}}]*\}}|\[[^\]]*\])", ASSETS.read_text(), re.S)
    assert m, name
    return m.group(1)


def test_web_earned_roles_equal_the_server():
    assert set(re.findall(r"'([a-z_]+)'", _ts("EARNED_ROLES"))) == set(E.EARNED_ROLES)


def test_web_transition_map_matches_the_server():
    """The web map decides which buttons exist; it had no driver_trainee entry."""
    web = dict(re.findall(r"(\w+):\s*\[([^\]]*)\]", _ts("ROLE_TRANSITIONS")))
    web = {k: tuple(re.findall(r"'([a-z_]+)'", v)) for k, v in web.items()}
    assert web == {k: tuple(v) for k, v in E.ROLE_TRANSITIONS.items()}


def test_the_typescript_request_matches_the_schema():
    """The drift that hid driver promotion for two months: one side's role list
    changed and the other's didn't. types.ts now mirrors the schema, pinned here."""
    from typing import get_args
    src = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text()
    m = re.search(r"interface RoleTransitionRequest \{[^}]*new_role:\s*([^;]+);", src, re.S)
    assert m, "RoleTransitionRequest missing from types.ts"
    ts_roles = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    py_roles = set(get_args(RoleTransitionRequest.model_fields["new_role"].annotation))
    assert ts_roles == py_roles
