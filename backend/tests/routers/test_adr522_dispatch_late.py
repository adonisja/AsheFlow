"""ADR-522 D4: the dispatch board's read runs the late check, for today only.

Before ADR-522 only the crew's `/truck/{id}/active` read flagged an overdue AP,
so with no crew member in the app a truck an hour past its ETA stayed
"preliminary" on the dispatch board and nobody was told.
"""
import asyncio
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.anchor_point import AnchorPoint
from app.models.anchor_point_late_flag import AnchorPointLateFlag
from app.models.notification import Notification
from app.routers import anchor_points as R
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_truck, sqlite_mirror_with_defaults,
)

TODAY = date.today() - timedelta(days=1)   # "today" for the company; an AM ETA on it is always past
EARLIER = TODAY - timedelta(days=1)


@pytest.fixture
def scene(db):
    for m in (AnchorPoint, AnchorPointLateFlag):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)
    driver = make_employee(db, role="driver", name="Alex Rivera")
    dispatch = make_employee(db, role="dispatch", name="Dee Dispatch")
    truck = make_truck(db, "Truck 12")
    for d in (TODAY, EARLIER):
        make_member(db, make_assignment(db, truck, d), driver, "driver")
    db.commit()
    return dict(driver=driver, dispatch=dispatch, truck=truck)


def _ap(db, scene, day, eta="9:00 AM"):
    ap = AnchorPoint(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=scene["truck"].id,
                     driver_id=scene["driver"].id, date=day, sequence=1, is_initial=True,
                     status="preliminary", location="W 43 ST & 10 AVE", eta=eta)
    db.add(ap); db.commit()
    return ap


def _read(db, scene, day):
    with patch.object(R, "company_today", return_value=TODAY), \
         patch("app.services.notify._enqueue"):
        return asyncio.run(R.get_anchor_points_for_date(day, db=db, caller=scene["dispatch"], _={}))


def _late_notifications(db):
    return db.query(Notification).filter(Notification.type == "anchor_point_running_late").all()


def test_the_board_flags_an_overdue_truck_today_and_tells_dispatch(db, scene):
    _ap(db, scene, TODAY)
    rows = _read(db, scene, TODAY)
    assert rows[0].is_running_late is True
    notes = _late_notifications(db)
    assert {n.employee_id for n in notes} >= {scene["dispatch"].id, scene["driver"].id}
    assert all(n.target_id == str(scene["truck"].id) for n in notes)   # ADR-519 link


def test_a_second_read_does_not_notify_again(db, scene):
    _ap(db, scene, TODAY)
    _read(db, scene, TODAY)
    first = len(_late_notifications(db))
    _read(db, scene, TODAY)
    assert len(_late_notifications(db)) == first
    assert db.query(AnchorPointLateFlag).count() == 1


def test_browsing_a_past_day_flags_nothing(db, scene):
    # _maybe_flag_late parses the ETA against the AP's own date, so without the
    # today-only guard every unarrived AP on a past day would be flagged.
    _ap(db, scene, EARLIER)
    rows = _read(db, scene, EARLIER)
    assert rows[0].is_running_late is False
    assert _late_notifications(db) == []


def test_a_lost_race_rolls_back_quietly(db, scene):
    ap = _ap(db, scene, TODAY)
    with patch.object(db, "flush", side_effect=IntegrityError("x", {}, Exception("unique"))), \
         patch("app.services.notify._enqueue"):
        raised = asyncio.run(R._raise_late_if_overdue(db, ap))
    assert raised is False
    assert _late_notifications(db) == []
