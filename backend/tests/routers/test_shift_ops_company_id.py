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
_WALKER = uuid.uuid4()
_TA = uuid.uuid4()
_DATE = date(2026, 7, 19)


def _caller():
    return SimpleNamespace(id=_DRIVER, company_id=_CID, role="driver", name="Test Driver")


def test_check_in_sets_company_id():
    added = {}
    db = MagicMock()
    db.add = lambda row: added.setdefault("row", row)
    # departure present, no existing check-in
    def _query(model):
        q = MagicMock()
        f = MagicMock()
        f.filter.return_value = f
        from app.models.field_ops import Departure
        f.first.return_value = SimpleNamespace() if model is Departure else None
        q.filter.return_value = f
        return q
    db.query = _query

    payload = DriverCheckInCreate(
        driver_id=_DRIVER, date=_DATE, check_in_number=1, routes_remaining=3,
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

def _crew_db(*, existing=None, member_on_crew=True):
    """Mock for upsert_crew_compliance_draft. member_row + members list come from
    AssignmentMember; existing CrewCompliance row optional."""
    from app.models.assignment_member import AssignmentMember
    from app.models.crew_compliance import CrewCompliance
    from app.models.truck_assignment import TruckAssignment

    member_row = SimpleNamespace(assignment_id=_TA)
    crew_members = [SimpleNamespace(employee_id=_WALKER)] if member_on_crew else []
    db = MagicMock()

    def _query(model):
        q = MagicMock(); q.join = MagicMock(return_value=q)
        f = MagicMock(); f.filter.return_value = f; f.join = MagicMock(return_value=f)
        if model is AssignmentMember:
            f.first.return_value = member_row
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


def _draft(db, uniform=True, cart=True):
    from app.routers.shift_ops import upsert_crew_compliance_draft
    from app.schemas.shift_ops import CrewComplianceDraftUpsert
    payload = CrewComplianceDraftUpsert(
        driver_id=_DRIVER, date=_DATE, employee_id=_WALKER,
        uniform_pass=uniform, cart_cover_pass=cart,
    )
    return upsert_crew_compliance_draft(payload=payload, db=db, _=None, caller=_caller())


def test_draft_creates_new_row_as_draft():
    db = _crew_db(existing=None)
    added = {}
    db.add = lambda r: added.setdefault("row", r)
    _draft(db, uniform=False, cart=True)
    row = added["row"]
    assert row.status == "draft"
    assert row.company_id == _CID
    assert row.uniform_pass is False and row.cart_cover_pass is True


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


def test_draft_rejects_non_crew_member():
    from fastapi import HTTPException
    db = _crew_db(member_on_crew=False)
    with pytest.raises(HTTPException) as exc:
        _draft(db)
    assert exc.value.status_code == 400


def test_draft_rejects_foreign_driver():
    from fastapi import HTTPException
    from app.routers.shift_ops import upsert_crew_compliance_draft
    from app.schemas.shift_ops import CrewComplianceDraftUpsert
    db = _crew_db()
    payload = CrewComplianceDraftUpsert(
        driver_id=uuid.uuid4(), date=_DATE, employee_id=_WALKER,   # not the caller
        uniform_pass=True, cart_cover_pass=True,
    )
    with pytest.raises(HTTPException) as exc:
        upsert_crew_compliance_draft(payload=payload, db=db, _=None, caller=_caller())
    assert exc.value.status_code == 403
