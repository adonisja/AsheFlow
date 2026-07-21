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
