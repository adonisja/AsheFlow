"""submit_roll_call authorization (ADR-202 change 2).

Trainer may roll-call any member of their own truck EXCEPT the driver (was:
paired trainee only). Driver may mark anyone on their truck. Off-truck → 403.

These exercise the authz gate, which raises before the status-derivation/upsert
path, so the DB mock only needs the lookups the gate performs.
"""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.roll_call import submit_roll_call
from app.schemas.roll_call import RollCallCreate


_CID = uuid.uuid4()
_TA = uuid.uuid4()
_DATE = date(2026, 7, 16)

_TRAINER = uuid.uuid4()
_WALKER = uuid.uuid4()
_TRAINEE = uuid.uuid4()
_DRIVER = uuid.uuid4()


def _caller(role, emp_id):
    c = MagicMock()
    c.id = emp_id
    c.company_id = _CID
    c.role = role
    return c


def _member(employee_id, role):
    return SimpleNamespace(employee_id=employee_id, role=role, assignment_id=_TA, company_id=_CID)


def _db(*, target_employee, target_am=None):
    """Mock Session for the authz gate. _get_caller_truck_assignment is patched
    separately (returns the caller's TA), so here we only serve:
    - Employee.first() → target employee (same company)
    - AssignmentMember.first() → target_am (the target-on-my-truck lookup)
    """
    db = MagicMock()

    def _query(model):
        from app.models.employee import Employee
        from app.models.assignment_member import AssignmentMember
        q = MagicMock()

        def _filter(*a, **k):
            f = MagicMock()
            f.join.return_value = f
            f.filter.return_value = f
            if model is Employee:
                f.first.return_value = target_employee
            elif model is AssignmentMember:
                f.first.return_value = target_am
            else:
                f.first.return_value = None
            return f

        q.filter = _filter
        q.join.return_value.filter = _filter
        return q

    db.query = _query
    return db


def _run(db, caller, target_id):
    body = RollCallCreate(employee_id=target_id, date=_DATE)
    # Patch the caller-truck helper so the gate sees the caller on truck _TA.
    with patch("app.routers.roll_call._get_caller_truck_assignment",
               return_value=SimpleNamespace(id=_TA)):
        return submit_roll_call(payload=body, caller=caller, db=db, _=None)


class TestTrainerRollCallAuthz:
    def test_trainer_can_mark_walker_on_truck(self):
        # Passes the authz gate → proceeds to status derivation. We stop it there
        # by making _get_company_cfg raise a sentinel, proving the gate let it through.
        target = SimpleNamespace(id=_WALKER, role="walker", company_id=_CID)
        db = _db(target_employee=target, target_am=_member(_WALKER, "walker"))
        with patch("app.routers.roll_call._get_company_cfg", side_effect=RuntimeError("passed-gate")):
            with pytest.raises(RuntimeError, match="passed-gate"):
                _run(db, _caller("trainer", _TRAINER), _WALKER)

    def test_trainer_can_mark_trainee_on_truck(self):
        target = SimpleNamespace(id=_TRAINEE, role="trainee", company_id=_CID)
        db = _db(target_employee=target, target_am=_member(_TRAINEE, "trainee"))
        with patch("app.routers.roll_call._get_company_cfg", side_effect=RuntimeError("passed-gate")):
            with pytest.raises(RuntimeError, match="passed-gate"):
                _run(db, _caller("trainer", _TRAINER), _TRAINEE)

    def test_trainer_cannot_mark_driver(self):
        target = SimpleNamespace(id=_DRIVER, role="driver", company_id=_CID)
        db = _db(target_employee=target, target_am=_member(_DRIVER, "driver"))
        with pytest.raises(HTTPException) as exc:
            _run(db, _caller("trainer", _TRAINER), _DRIVER)
        assert exc.value.status_code == 403
        assert "driver" in exc.value.detail.lower()

    def test_field_caller_target_not_on_truck(self):
        target = SimpleNamespace(id=_WALKER, role="walker", company_id=_CID)
        db = _db(target_employee=target, target_am=None)   # not on caller's truck
        with pytest.raises(HTTPException) as exc:
            _run(db, _caller("trainer", _TRAINER), _WALKER)
        assert exc.value.status_code == 403
        assert "your truck" in exc.value.detail.lower()

    def test_driver_can_mark_driver(self):
        # A driver marking the driver slot is allowed (no trainer restriction).
        target = SimpleNamespace(id=_DRIVER, role="driver", company_id=_CID)
        db = _db(target_employee=target, target_am=_member(_DRIVER, "driver"))
        with patch("app.routers.roll_call._get_company_cfg", side_effect=RuntimeError("passed-gate")):
            with pytest.raises(RuntimeError, match="passed-gate"):
                _run(db, _caller("driver", _DRIVER), _DRIVER)


# ── Conflict rule on existing records (ADR-208) ──────────────────────────────
# Field staff latest-wins on their own truck, but a dispatch/admin mark locks it.
# Uses ncns=True so the upsert branch is reached without status derivation.

class TestRollCallConflictRule:
    def _existing(self, last_writer_id):
        # A ShiftRollCall row already present for the target/date (all fields the
        # RollCallResponse serializer needs so the endpoint can return it).
        from datetime import datetime, timezone
        return SimpleNamespace(
            id=uuid.uuid4(), company_id=_CID, employee_id=_WALKER, date=_DATE,
            status="present", notes=None, submitted_by_id=last_writer_id,
            submitted_at=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
            updated_by_id=None, updated_at=None, confirmed=True, confirmed_at=None,
        )

    def _db_with_existing(self, *, target, existing, writers):
        """target Employee + AssignmentMember for the gate; ShiftRollCall.first()
        → existing; Employee lookups resolved from `writers` {id: employee} for the
        last-writer check (falls back to target)."""
        from app.models.employee import Employee
        from app.models.assignment_member import AssignmentMember
        from app.models.shift_roll_call import ShiftRollCall
        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*a, **k):
                f = MagicMock()
                f.join.return_value = f
                f.filter.return_value = f
                if model is Employee:
                    # Resolve by the id in the filter args when possible; the gate
                    # looks up the target, the conflict check looks up the writer.
                    f.first.return_value = writers.get('_next', target)
                elif model is AssignmentMember:
                    f.first.return_value = _member(target.id, target.role)
                elif model is ShiftRollCall:
                    f.first.return_value = existing
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            q.join.return_value.filter = _filter
            return q
        db.query = _query
        return db

    def _run_ncns(self, db, caller, target_id):
        body = RollCallCreate(employee_id=target_id, date=_DATE, ncns=True)
        with patch("app.routers.roll_call._get_caller_truck_assignment",
                   return_value=SimpleNamespace(id=_TA)), \
             patch("app.routers.roll_call.write_audit"):
            return submit_roll_call(payload=body, caller=caller, db=db, _=None)

    def test_field_staff_can_override_field_set_record(self):
        # Existing record last written by a TRAINER → a driver may update it (latest-wins).
        target = SimpleNamespace(id=_WALKER, role="walker", company_id=_CID)
        existing = self._existing(last_writer_id=_TRAINER)
        writer = SimpleNamespace(id=_TRAINER, role="trainer", company_id=_CID)
        # Employee lookups: gate wants target; conflict check wants the trainer writer.
        # Serve target for the gate, then the writer for the conflict lookup.
        db = self._db_with_existing(target=target, existing=existing,
                                    writers={'_next': writer})
        # Gate's Employee lookup also hits this — acceptable since both are same company;
        # the conflict lookup returns a trainer (field peer) → update allowed, no raise.
        result = self._run_ncns(db, _caller("driver", _DRIVER), _WALKER)
        assert existing.status == "ncns"           # updated in place
        assert existing.updated_by_id == _DRIVER    # latest writer stamped
        assert result.status == "ncns"              # returned serialized row

    def test_field_staff_blocked_on_dispatch_set_record(self):
        # Existing record last written by DISPATCH → a driver gets 409 (locked).
        target = SimpleNamespace(id=_WALKER, role="walker", company_id=_CID)
        existing = self._existing(last_writer_id=uuid.uuid4())
        dispatcher = SimpleNamespace(id=existing.submitted_by_id, role="dispatch", company_id=_CID)
        db = self._db_with_existing(target=target, existing=existing,
                                    writers={'_next': dispatcher})
        with pytest.raises(HTTPException) as exc:
            self._run_ncns(db, _caller("driver", _DRIVER), _WALKER)
        assert exc.value.status_code == 409
        assert "dispatch" in exc.value.detail.lower()

    def test_dispatch_always_overrides(self):
        # Dispatch caller overrides any existing record regardless of last writer.
        target = SimpleNamespace(id=_WALKER, role="walker", company_id=_CID)
        existing = self._existing(last_writer_id=uuid.uuid4())
        db = self._db_with_existing(target=target, existing=existing, writers={})
        result = self._run_ncns(db, _caller("dispatch", uuid.uuid4()), _WALKER)
        assert existing.status == "ncns"
        assert result.status == "ncns"
