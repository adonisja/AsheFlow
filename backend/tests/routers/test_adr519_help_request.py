"""ADR-519: 'Driver Needs Help' opens that one help request.

End to end: a driver's check-in with help_requested writes a notification whose
link opens /help-requests/<that check-in>, and the endpoint behind it returns
the request to oversight only, company scoped, with the driver's phone per
ADR-458 (field staff shown, office not).
"""
import uuid
from datetime import date
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.driver_check_in import DriverCheckIn
from app.models.field_ops import Departure
from app.models.notification import Notification
from app.routers import shift_ops as S
from app.schemas.notification import NotificationResponse
from app.schemas.shift_ops import DriverCheckInCreate
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_truck, sqlite_mirror_with_defaults,
)

DAY = date(2026, 10, 15)


@pytest.fixture
def scene(db):
    for m in (DriverCheckIn, Departure):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)
    driver = make_employee(db, role="driver", name="Alex Rivera")
    driver.phone_number = "555-0100"
    dispatch = make_employee(db, role="dispatch", name="Dee Dispatch")
    walker = make_employee(db, role="walker", name="Wally Walker")
    truck = make_truck(db, "Truck 12")
    ta = make_assignment(db, truck, DAY)
    make_member(db, ta, driver, "driver")
    db.add(Departure(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=driver.id, date=DAY))
    db.commit()
    return dict(driver=driver, dispatch=dispatch, walker=walker, truck=truck)


def _ask_for_help(db, driver):
    body = DriverCheckInCreate(driver_id=driver.id, date=DAY, check_in_number=2,
                               routes_remaining=4, help_requested=True, working_crew_count=3)
    with patch("app.services.notify._enqueue"):
        S.submit_driver_check_in(body, db=db, _={}, caller=driver)
    return db.query(DriverCheckIn).one()


def test_the_alert_opens_that_help_request(db, scene):
    row = _ask_for_help(db, scene["driver"])
    n = db.query(Notification).filter_by(type="driver_help_requested", employee_id=scene["dispatch"].id).one()
    assert n.target_id == str(row.id), "the id must exist before the notification is written (ADR-510)"
    link = NotificationResponse.from_row(n).link
    assert link.route == f"/help-requests/{row.id}" and link.kind == "help_request"


def test_oversight_reads_the_request_with_driver_truck_and_phone(db, scene):
    row = _ask_for_help(db, scene["driver"])
    out = S.get_help_request(row.id, db=db, caller=scene["dispatch"], _={})
    assert out["driver"] == {"id": str(scene["driver"].id), "name": "Alex Rivera", "phone": "555-0100"}
    assert out["truck"]["name"] == "Truck 12"
    assert (out["check_in_number"], out["routes_remaining"], out["working_crew_count"]) == (2, 4, 3)


def test_an_office_drivers_phone_is_not_shown(db, scene):
    row = _ask_for_help(db, scene["driver"])
    scene["driver"].role = "management"   # an owner covering a route (ADR-458: office rows hide it)
    db.commit()
    assert S.get_help_request(row.id, db=db, caller=scene["dispatch"], _={})["driver"]["phone"] is None


def test_a_check_in_that_did_not_ask_for_help_is_not_a_help_request(db, scene):
    row = DriverCheckIn(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, driver_id=scene["driver"].id, date=DAY,
                        check_in_number=3, routes_remaining=1, help_requested=False, working_crew_count=3)
    db.add(row); db.commit()
    with pytest.raises(HTTPException) as e:
        S.get_help_request(row.id, db=db, caller=scene["dispatch"], _={})
    assert e.value.status_code == 404


def test_another_companys_request_is_not_found(db, scene):
    row = _ask_for_help(db, scene["driver"])
    stranger = make_employee(db, role="dispatch", name="Other Co")
    stranger.company_id = uuid.uuid4()
    db.commit()
    with pytest.raises(HTTPException) as e:
        S.get_help_request(row.id, db=db, caller=stranger, _={})
    assert e.value.status_code == 404


def test_only_oversight_may_open_it():
    import inspect
    gate = inspect.signature(S.get_help_request).parameters["_"].default.dependency
    assert set(gate.allowed_roles) == {"dispatch", "management", "admin"}
