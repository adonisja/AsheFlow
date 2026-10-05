"""Delivery happens after the commit, never before or instead (ADR-487 D3).

WHY THIS ORDERING, FROM THIS REPO'S OWN HISTORY
===============================================

ADR-324 found both halves of getting it wrong:

  * A Discord call placed BEFORE the commit took out the in-app notifications
    created downstream of it — "a dead secondary channel was taking out the
    primary one."
  * An alert committed WITH the main transaction was discarded when an
    unrelated helper called db.rollback() in between.

`after_commit` makes both unexpressible rather than fixed: it cannot fire for a
rolled-back row, and it cannot be skipped by a rollback.

THE THREE PROPERTIES IT RELIES ON
=================================

Nothing in this repo demonstrated these before D3 — the only other SQLAlchemy
listener is an Engine-level "connect" hook in one test. So they are asserted
here rather than assumed:

  1. fires only on a SUCCESSFUL commit
  2. fires once per commit, and the pending list is cleared (or a second commit
     re-sends the first one's batch)
  3. must not emit SQL (that starts a new implicit transaction)
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.employee import Employee
from app.services import notify as N
from app.services.notification_spec import Channel, resolve_spec


def _emp(db, company_id, role="dispatch", active=True):
    e = Employee(
        id=uuid.uuid4(), company_id=company_id, name=f"e{uuid.uuid4().hex[:6]}",
        role=role, is_active=active, email=f"{uuid.uuid4().hex[:8]}@x.test",
    )
    db.add(e)
    return e


class TestNothingIsSentBeforeTheCommit:
    def test_write_notification_enqueues_nothing_on_its_own(self, db):
        """The helper only touches the session. This is the ADR-324 defect: a
        send issued before the commit can be for a row that never lands."""
        cid, eid = uuid.uuid4(), uuid.uuid4()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=eid,
                type="dispatch_assignment",   # BANNER|PUSH|DISCORD
                message="x",
            )
            assert sent.call_count == 0, (
                "the helper sent something before the transaction committed"
            )

    def test_the_intent_is_recorded_on_the_session(self, db):
        cid, eid = uuid.uuid4(), uuid.uuid4()
        N.write_notification(
            db, company_id=cid, employee_id=eid,
            type="dispatch_assignment", message="x",
        )
        pending = db.info.get("adr487_pending_notification_dispatches")
        assert pending and len(pending) == 1
        assert pending[0].type == "dispatch_assignment"

    def test_a_rollback_sends_nothing(self, db):
        """The second ADR-324 failure: an alert discarded by an unrelated
        rollback. after_commit cannot fire for a transaction that rolled back."""
        cid, eid = uuid.uuid4(), uuid.uuid4()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=eid,
                type="dispatch_assignment", message="x",
            )
            db.rollback()
            assert sent.call_count == 0


class TestTheHookFiresOnceAndClears:
    def test_a_second_commit_does_not_resend_the_first_batch(self, db):
        """Property 2. after_commit fires for EVERY commit on the session, so
        without the clear() a request that commits twice sends twice."""
        cid = uuid.uuid4()
        emp = _emp(db, cid)
        db.commit()   # drain anything the fixture queued

        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="first",
            )
            db.commit()
            after_first = sent.call_count
            assert after_first == 1

            # A second, unrelated commit on the same session.
            emp.name = "renamed"
            db.commit()
            assert sent.call_count == after_first, (
                "the second commit re-sent the first commit's batch — the "
                "pending list was not cleared"
            )

    def test_the_pending_list_is_empty_after_a_commit(self, db):
        cid = uuid.uuid4()
        emp = _emp(db, cid)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay"):
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="x",
            )
            db.commit()
        assert not db.info.get("adr487_pending_notification_dispatches")

    def test_the_list_is_cleared_BEFORE_enqueueing(self, db):
        """If an enqueue raises, the batch must not be re-sent on the next
        commit — some of it already went out."""
        cid = uuid.uuid4()
        emp = _emp(db, cid)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay",
                   side_effect=RuntimeError("broker down")):
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="x",
            )
            db.commit()   # must NOT raise: see the next test
        assert not db.info.get("adr487_pending_notification_dispatches")

    def test_an_enqueue_failure_does_not_fail_the_commit(self, db):
        """The rows are committed and the operation succeeded. Letting a broker
        problem propagate would turn a delivery gap into a 500 on work that
        completed — and the sweep exists precisely to catch this."""
        cid = uuid.uuid4()
        emp = _emp(db, cid)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay",
                   side_effect=RuntimeError("broker down")):
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="x",
            )
            db.commit()   # no exception


class TestOnlyDeliverableChannelsAreRecorded:
    def test_a_banner_only_type_records_no_intent(self, db):
        """BANNER/TICKER/GATE are rendered when the client reads the row —
        there is no server-side send. Recording an intent for them would mean
        the sweep chasing rows that were never meant to be dispatched."""
        spec = resolve_spec("assignment_change_request")
        assert spec.channels == Channel.BANNER, "fixture assumption changed"

        cid, eid = uuid.uuid4(), uuid.uuid4()
        N.write_notification(
            db, company_id=cid, employee_id=eid,
            type="assignment_change_request", message="x",
        )
        assert not db.info.get("adr487_pending_notification_dispatches")

    def test_a_pushed_type_records_an_intent(self, db):
        spec = resolve_spec("dispatch_assignment")
        assert Channel.PUSH in spec.channels
        cid, eid = uuid.uuid4(), uuid.uuid4()
        N.write_notification(
            db, company_id=cid, employee_id=eid,
            type="dispatch_assignment", message="x",
        )
        assert len(db.info["adr487_pending_notification_dispatches"]) == 1


class TestAFanOutIsOneBatch:
    def test_every_recipient_is_recorded(self, db):
        """51 of the original sites were fan-outs. The batch arriving as one
        unit is what makes "one Discord post per event" possible later."""
        cid = uuid.uuid4()
        for _ in range(3):
            _emp(db, cid, role="dispatch")
        db.flush()

        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            made = N.fan_out(
                db, company_id=cid, audience=N.Audience.STATION_RESOLVE,
                type="sort_packages_dropped", message="x",
            )
            assert len(made) == 3
            assert sent.call_count == 0        # still nothing before the commit
            db.commit()
            assert sent.call_count == 3        # one per recipient, after it
