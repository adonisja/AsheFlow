"""shift_ops check-in / crew-compliance must set company_id (regression).

DriverCheckIn.company_id and CrewCompliance.company_id are NOT NULL but were never
set from the caller — every submit raised an IntegrityError 500. These pin that the
constructed rows carry the caller's company_id.
"""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.routers.shift_ops import submit_driver_check_in, submit_crew_compliance
from app.schemas.shift_ops import DriverCheckInCreate, CrewComplianceCreate, CrewComplianceEntry

_CID = uuid.uuid4()
_DRIVER = uuid.uuid4()
_TRAINER = uuid.uuid4()
_WALKER = uuid.uuid4()
_TA = uuid.uuid4()
_DATE = date(2026, 7, 19)


def _caller():
    return SimpleNamespace(id=_DRIVER, company_id=_CID, role="driver", name="Test Driver")


def test_check_in_sets_company_id():
    # check_in_number=2: exercises the company_id regression WITHOUT the ADR-228
    # roster gate (which only runs on #1). The gate is covered separately below.
    added = {}
    db = MagicMock()
    db.add = lambda row: added.setdefault("row", row)
    # departure present, no existing check-in
    def _query(*models):
        q = MagicMock()
        f = MagicMock()
        f.filter.return_value = f
        from app.models.field_ops import Departure
        f.first.return_value = SimpleNamespace() if models[0] is Departure else None
        q.filter.return_value = f
        return q
    db.query = _query

    payload = DriverCheckInCreate(
        driver_id=_DRIVER, date=_DATE, check_in_number=2, routes_remaining=3,
        help_requested=False, working_crew_count=3, ncns_count=0,
    )
    submit_driver_check_in(payload=payload, db=db, _=None, caller=_caller())
    assert added["row"].company_id == _CID


def test_help_requested_notifies_dispatch():
    # ADR-215: help_requested=true → a Notification per active dispatch/mgmt/admin.
    from app.models.field_ops import Departure
    from app.models.employee import Employee
    from app.models.notification import Notification
    added: list = []
    db = MagicMock()
    db.add = lambda row: added.append(row)
    dispatchers = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]

    def _query(model):
        q = MagicMock(); f = MagicMock(); f.filter.return_value = f
        if model is Departure:
            f.first.return_value = SimpleNamespace()
            f.all.return_value = []
        elif model is Employee:
            f.all.return_value = dispatchers      # dispatch recipients
            f.first.return_value = None
        else:
            f.first.return_value = None
            f.all.return_value = []
        q.filter.return_value = f
        return q
    db.query = _query

    payload = DriverCheckInCreate(
        driver_id=_DRIVER, date=_DATE, check_in_number=3, routes_remaining=44,
        help_requested=True, working_crew_count=29, ncns_count=0,
    )
    submit_driver_check_in(payload=payload, db=db, _=None, caller=_caller())
    notifs = [r for r in added if isinstance(r, Notification)]
    assert len(notifs) == 2
    assert all(n.type == "driver_help_requested" and n.company_id == _CID for n in notifs)


def test_no_help_no_notification():
    from app.models.field_ops import Departure
    from app.models.employee import Employee
    from app.models.notification import Notification
    added: list = []
    db = MagicMock()
    db.add = lambda row: added.append(row)

    def _query(model):
        q = MagicMock(); f = MagicMock(); f.filter.return_value = f
        f.first.return_value = SimpleNamespace() if model is Departure else None
        f.all.return_value = [SimpleNamespace(id=uuid.uuid4())] if model is Employee else []
        q.filter.return_value = f
        return q
    db.query = _query

    payload = DriverCheckInCreate(
        driver_id=_DRIVER, date=_DATE, check_in_number=2, routes_remaining=10,
        help_requested=False, working_crew_count=5, ncns_count=0,
    )
    submit_driver_check_in(payload=payload, db=db, _=None, caller=_caller())
    assert not [r for r in added if isinstance(r, Notification)]


def test_crew_compliance_sets_company_id():
    added = []
    db = MagicMock()
    db.add = lambda row: added.append(row)
    from app.models.assignment_member import AssignmentMember
    from app.models.crew_compliance import CrewCompliance

    def _query(model):
        q = MagicMock()
        q.join.return_value = q
        f = MagicMock()
        f.filter.return_value = f
        if model is AssignmentMember:
            # member_row lookup → driver on _TA; crew list → the walker
            f.first.return_value = SimpleNamespace(assignment_id=_TA)
            f.all.return_value = [SimpleNamespace(employee_id=_WALKER)]
        elif model is CrewCompliance:
            f.first.return_value = None  # no duplicate
        else:
            f.first.return_value = None
            f.all.return_value = []
        q.filter.return_value = f
        return q
    db.query = _query

    payload = CrewComplianceCreate(
        driver_id=_DRIVER, date=_DATE,
        entries=[CrewComplianceEntry(employee_id=_WALKER, uniform_pass=True, cart_cover_pass=True)],
    )
    submit_crew_compliance(payload=payload, db=db, _=None, caller=_caller())
    assert added and all(row.company_id == _CID for row in added)


# ── ADR-228: draft compliance upsert (Crew Roster live capture) ──────────────

def _crew_db(*, existing=None, caller_on_truck=True, has_driver=True):
    """Mock for upsert_crew_compliance_draft. The endpoint resolves the caller's
    truck (my_row), its members (incl. the driver), and any existing compliance."""
    from app.models.assignment_member import AssignmentMember
    from app.models.crew_compliance import CrewCompliance

    my_row = SimpleNamespace(assignment_id=_TA) if caller_on_truck else None
    crew_members = [SimpleNamespace(employee_id=_WALKER, role="walker")]
    if has_driver:
        crew_members.append(SimpleNamespace(employee_id=_DRIVER, role="driver"))
    db = MagicMock()

    def _query(model):
        q = MagicMock(); q.join = MagicMock(return_value=q)
        f = MagicMock(); f.filter.return_value = f; f.join = MagicMock(return_value=f)
        if model is AssignmentMember:
            f.first.return_value = my_row
            f.all.return_value = crew_members
        elif model is CrewCompliance:
            f.first.return_value = existing
        else:
            f.first.return_value = None; f.all.return_value = []
        q.filter = MagicMock(return_value=f)
        return q
    db.query = _query
    db.add = MagicMock(); db.commit = MagicMock(); db.refresh = MagicMock()
    return db


def _draft(db, uniform=True, cart=True, caller=None, employee_id=_WALKER):
    from app.routers.shift_ops import upsert_crew_compliance_draft
    from app.schemas.shift_ops import CrewComplianceDraftUpsert
    payload = CrewComplianceDraftUpsert(
        date=_DATE, employee_id=employee_id,
        uniform_pass=uniform, cart_cover_pass=cart,
    )
    return upsert_crew_compliance_draft(payload=payload, db=db, _=None, caller=caller or _caller())


def test_draft_creates_new_row_keyed_to_driver():
    # Caller is the DRIVER; record is keyed to the resolved driver_id (_DRIVER).
    db = _crew_db(existing=None)
    added = {}
    db.add = lambda r: added.setdefault("row", r)
    _draft(db, uniform=False, cart=True)
    row = added["row"]
    assert row.status == "draft"
    assert row.company_id == _CID
    assert row.driver_id == _DRIVER
    assert row.uniform_pass is False and row.cart_cover_pass is True


def test_trainer_captain_can_record_keyed_to_driver():
    # A TRAINER on the same truck records compliance; the record still keys to the
    # truck's DRIVER (resolved server-side), not the trainer.
    trainer = SimpleNamespace(id=_TRAINER, company_id=_CID, role="trainer", name="Cap")
    db = _crew_db(existing=None)
    added = {}
    db.add = lambda r: added.setdefault("row", r)
    _draft(db, uniform=True, cart=False, caller=trainer)
    assert added["row"].driver_id == _DRIVER          # keyed to driver, not the trainer caller


def test_draft_can_target_a_trainer_member():
    # Compliance applies to EVERY present member incl. trainers.
    db = _crew_db(existing=None)
    added = {}
    db.add = lambda r: added.setdefault("row", r)
    _draft(db, employee_id=_DRIVER)   # the driver is a crew member too; any member works
    assert added["row"].employee_id == _DRIVER


def test_draft_updates_existing_draft():
    existing = SimpleNamespace(
        status="draft", uniform_pass=True, cart_cover_pass=True, arrival_time=None,
    )
    db = _crew_db(existing=existing)
    _draft(db, uniform=False, cart=False)
    assert existing.uniform_pass is False and existing.cart_cover_pass is False


def test_draft_does_not_downgrade_submitted():
    existing = SimpleNamespace(
        status="submitted", uniform_pass=True, cart_cover_pass=True, arrival_time=None,
    )
    db = _crew_db(existing=existing)
    _draft(db, uniform=False, cart=False)
    # already finalized → left untouched
    assert existing.uniform_pass is True and existing.cart_cover_pass is True


def test_draft_rejects_caller_not_on_truck():
    from fastapi import HTTPException
    db = _crew_db(caller_on_truck=False)
    with pytest.raises(HTTPException) as exc:
        _draft(db)
    assert exc.value.status_code == 400


def test_draft_rejects_truck_without_driver():
    from fastapi import HTTPException
    db = _crew_db(has_driver=False)
    with pytest.raises(HTTPException) as exc:
        _draft(db)
    assert exc.value.status_code == 409


# ── ADR-228 WS4: Check-In #1 roster-complete gate + finalize ─────────────────

def _roster_db(*, crew, roll, comp):
    """Mock for _assert_roster_complete_and_finalize.
      crew: list of (employee_id, role, name)
      roll: {employee_id: status}
      comp: {employee_id: SimpleNamespace(status, uniform_pass, cart_cover_pass)}
    """
    from app.models.assignment_member import AssignmentMember
    from app.models.employee import Employee
    from app.models.shift_roll_call import ShiftRollCall
    from app.models.crew_compliance import CrewCompliance

    my_row = SimpleNamespace(assignment_id=_TA)
    member_emp_rows = [
        (SimpleNamespace(employee_id=eid, role=role), SimpleNamespace(id=eid, name=name))
        for eid, role, name in crew
    ]
    roll_rows = [SimpleNamespace(employee_id=eid, status=st) for eid, st in roll.items()]
    comp_rows = list(comp.values())
    db = MagicMock()

    def _query(*models):
        model = models[0]
        q = MagicMock(); q.join = MagicMock(return_value=q)
        f = MagicMock(); f.filter.return_value = f; f.join = MagicMock(return_value=f)
        if model is AssignmentMember and len(models) == 1:
            f.first.return_value = my_row
        elif model is AssignmentMember:                # join(AssignmentMember, Employee)
            f.all.return_value = member_emp_rows
        elif model is ShiftRollCall:
            f.all.return_value = roll_rows
        elif model is CrewCompliance:
            f.all.return_value = comp_rows
        else:
            f.first.return_value = None; f.all.return_value = []
        q.filter = MagicMock(return_value=f)
        return q
    db.query = _query
    return db


def _comp(eid, status="draft", uniform=True, cart=True):
    return SimpleNamespace(employee_id=eid, status=status, uniform_pass=uniform, cart_cover_pass=cart)


def _run_gate(db):
    from app.routers.shift_ops import _assert_roster_complete_and_finalize
    return _assert_roster_complete_and_finalize(db, _DRIVER, _DATE, _CID)


def test_roster_gate_complete_finalizes_drafts():
    w1, w2 = _WALKER, _TRAINER
    comp = {w1: _comp(w1, "draft", uniform=True, cart=True),
            w2: _comp(w2, "draft", uniform=False, cart=True)}
    db = _roster_db(
        crew=[(_DRIVER, "driver", "Drv"), (w1, "walker", "Wa"), (w2, "trainer", "Tr")],
        roll={w1: "present", w2: "late"},
        comp=comp,
    )
    summary = _run_gate(db)
    assert summary["present"] == 2 and summary["ncns"] == 0
    assert summary["finalized"] == 2
    assert comp[w1].status == "submitted" and comp[w2].status == "submitted"
    assert summary["compliance_fails"] == 1     # w2 failed uniform


def test_roster_gate_ncns_needs_no_compliance():
    db = _roster_db(
        crew=[(_DRIVER, "driver", "Drv"), (_WALKER, "walker", "Wa")],
        roll={_WALKER: "ncns"},        # absent → no compliance required
        comp={},
    )
    summary = _run_gate(db)
    assert summary["present"] == 0 and summary["ncns"] == 1


def test_roster_gate_blocks_unrolled_member():
    from fastapi import HTTPException
    db = _roster_db(
        crew=[(_DRIVER, "driver", "Drv"), (_WALKER, "walker", "Wanda")],
        roll={},                       # nobody rolled
        comp={},
    )
    with pytest.raises(HTTPException) as exc:
        _run_gate(db)
    assert exc.value.status_code == 422
    assert any("not rolled" in p for p in exc.value.detail["problems"])
    assert "Wanda" in str(exc.value.detail["problems"])


def test_roster_gate_blocks_present_without_compliance():
    from fastapi import HTTPException
    db = _roster_db(
        crew=[(_DRIVER, "driver", "Drv"), (_WALKER, "walker", "Wanda")],
        roll={_WALKER: "present"},
        comp={},                       # present but no uniform/cart-cover
    )
    with pytest.raises(HTTPException) as exc:
        _run_gate(db)
    assert exc.value.status_code == 422
    assert any("uniform" in p for p in exc.value.detail["problems"])
