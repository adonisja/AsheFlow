"""ADR-510 — a notification has its id before its delivery is recorded.

End to end, through the commit hook: the exact path that was broken. The push
test on 2026-10-12 called send_push.run(<real id>) directly and so never saw
that the normal path handed the task the string "None".
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.notification import Notification
from app.services import notify as N
from app.services.notification_spec import SPEC, Channel
from tests.conftest import make_employee

PUSH_TYPE = "anchor_point_running_late"   # BANNER | PUSH | DISCORD


@pytest.fixture(autouse=True)
def production_autoflush(db):
    """Run with PRODUCTION's session setting. app/database.py builds SessionLocal
    with autoflush=False; conftest's sessionmaker defaults to autoflush=True.
    With autoflush on, the Discord-id lookup inside write_notification flushes
    the new row and gives it an id just in time, so every test passed while
    production recorded "None". The first version of this file did exactly
    that: the probe that removed the fix passed all four tests."""
    db.autoflush = False
    yield


def test_the_type_used_really_pushes():
    assert Channel.PUSH in SPEC[PUSH_TYPE].channels


def test_write_notification_hands_push_the_real_id(db):
    emp = make_employee(db)
    emp.discord_id = "123456789012345678"
    db.commit()
    with patch("app.tasks.push_delivery_task.send_push.delay") as push, \
         patch("app.tasks.discord_delivery.send_discord.delay") as discord:
        n = N.write_notification(db, company_id=emp.company_id, employee_id=emp.id,
                                 type=PUSH_TYPE, message="Truck 12 is running late")
        db.commit()
    assert push.call_count == 1
    sent_id = push.call_args.args[0]
    assert sent_id != "None", "the defect: the delivery was recorded before the id existed"
    assert sent_id == str(n.id)
    assert db.get(Notification, n.id) is not None, "the id the task gets must find the row"
    assert discord.call_args.kwargs["notification_id"] == str(n.id), (
        "Discord stamps dispatched_at by this id; 'None' stamps nothing"
    )


def test_fan_out_hands_each_push_its_own_real_id(db):
    a = make_employee(db, role="dispatch", name="A")
    make_employee(db, role="dispatch", name="B")
    with patch("app.tasks.push_delivery_task.send_push.delay") as push, \
         patch("app.tasks.discord_delivery.send_discord.delay"):
        rows = N.fan_out(db, company_id=a.company_id, audience=("dispatch",),
                         type=PUSH_TYPE, message="x")
        db.commit()
    sent = sorted(c.args[0] for c in push.call_args_list)
    assert sent == sorted(str(r.id) for r in rows) and "None" not in sent


def test_recording_a_delivery_without_an_id_fails_loudly(db):
    emp = make_employee(db)
    n = Notification(_via_helper=True, company_id=emp.company_id, employee_id=emp.id,
                     type=PUSH_TYPE, message="x")          # no id, as before ADR-510
    with pytest.raises(ValueError, match="ADR-510"):
        N._record_intent(db, SPEC[PUSH_TYPE], n)
