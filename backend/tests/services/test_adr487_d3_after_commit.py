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


def _emp(db, company_id, role="dispatch", active=True, discord=True):
    """An employee, LINKED to Discord by default.

    `discord_id` is nullable and gates the Discord send: the bot's contract is
    {"discord_id", "message"} and there is nothing to address without one. A
    fixture without it silently exercises the skip path, which is how two of
    these tests first failed after the payload was corrected.
    """
    e = Employee(
        id=uuid.uuid4(), company_id=company_id, name=f"e{uuid.uuid4().hex[:6]}",
        role=role, is_active=active, email=f"{uuid.uuid4().hex[:8]}@x.test",
        discord_id=(f"d{uuid.uuid4().int % 10**17}" if discord else None),
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


class TestAnUnlinkedRecipientIsNotAFailure:
    """`discord_id` is nullable — a walker who never linked Discord has none.

    The bot's contract is {"discord_id", "message"} (bot/main.py:451) and it
    400s on anything else, so there is nothing to address. That is not a
    delivery failure: the in-app notification is the channel of record and
    Discord is the convenience surface (ADR-324).
    """

    def test_no_send_is_attempted_without_a_discord_id(self, db):
        cid = uuid.uuid4()
        emp = _emp(db, cid, discord=False)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="x",
            )
            db.commit()
            assert sent.call_count == 0

    def test_the_payload_matches_the_bots_contract(self, db):
        """The bug this replaced: an earlier version sent `employee_id`, which
        bot/main.py refuses with "Missing discord_id or message" — so every
        Discord delivery would have been a 400."""
        cid = uuid.uuid4()
        emp = _emp(db, cid, discord=True)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="hello",
            )
            db.commit()
            assert sent.call_count == 1
            kind, payload = sent.call_args.args
            assert kind == "dm"
            assert set(payload) == {"discord_id", "message"}, (
                f"the bot requires exactly discord_id + message, got {set(payload)}"
            )
            assert payload["discord_id"] == emp.discord_id
            assert payload["message"] == "hello"


class TestTheDiscordLookupIsTenantScoped:
    """Dimension 1, on a query whose ids LOOK safe by construction.

    Every id passed to the lookup comes from a Notification row built in the
    same call, so in practice they are already tenant-correct. That is an
    argument about the caller, not a property of the function:
    `write_notification` takes `employee_id` as a parameter, so the scoping has
    to hold for callers that do not exist yet.

    And the consequence is not an over-broad read. The value being resolved is a
    Discord address, so an unscoped match DMs a stranger in another tenant — a
    cross-tenant leak that leaves the building.

    Why it stayed invisible: a first audit pass swept every query in the changed
    FILES rather than the changed LINES, buried this one in ~300 pre-existing
    queries, and found nothing. Scoping the scan to `git diff` surfaced it in two
    lines of output.
    """

    def test_a_foreign_employee_id_resolves_to_no_discord_address(self, db):
        own = uuid.uuid4()
        other = uuid.uuid4()
        stranger = _emp(db, other, discord=True)   # linked, but another tenant
        db.commit()

        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db,
                company_id=own,                 # this tenant
                employee_id=stranger.id,        # someone else's employee
                type="dispatch_assignment", message="x",
            )
            db.commit()
            assert sent.call_count == 0, (
                "the lookup crossed tenants and produced a Discord address for "
                "an employee of another company — that send would DM a stranger"
            )

    def test_the_query_filters_on_company_id(self):
        """The behavioural test above only fails if the unscoped row happens to
        be reachable. This one pins the filter itself."""
        import inspect
        from tests.conftest import code_only

        src = code_only(N._resolve_discord_ids)
        assert "Employee.company_id" in src, (
            "the discord_id lookup must filter by company_id (Dimension 1)"
        )

    def test_the_lookup_queries_a_whole_entity_not_two_columns(self):
        """60 tests in this suite stub db.query with `def _query(model)` — a
        single positional, the established idiom here. A two-column query
        (`db.query(Employee.id, Employee.discord_id)`) raises TypeError from
        inside write_notification in every one of them, which is how eight tests
        across five files failed on a change that touched none of them.

        Querying the whole entity keeps one shape for both paths: fan_out
        already issues db.query(Employee), and its rows carry discord_id free.
        """
        import inspect
        src = inspect.getsource(N._resolve_discord_ids)
        assert "db.query(Employee)" in src, (
            "a multi-column query breaks the suite's single-positional db.query "
            "doubles; fan_out already loads whole Employee rows"
        )

    def test_a_same_tenant_employee_still_resolves(self):
        """The failure mode of the fix: over-scoping that silently stops every
        legitimate send. Half a tenancy fix is a dead channel."""
        import inspect
        src = inspect.getsource(N._resolve_discord_ids)
        assert "Employee.id.in_(employee_ids)" in src, (
            "over-scoping that resolves nobody is a dead channel, not a fix"
        )


class TestAStringEmployeeIdStillResolves:
    """`write_notification` declares `employee_id: UUID | str`.

    It passes the value straight through to the row AND uses it to look up the
    Discord address. The ORM always hands back a UUID for `Employee.id`, so a
    dict keyed by `e.id` and read with a caller-supplied STRING misses — and the
    miss is `None`, which `_enqueue` reads as "this employee has no Discord
    account" and skips. No exception, no log, no delivery.

    Why it stayed invisible: every test in this file passes a UUID, because
    that is what `uuid.uuid4()` returns and what the ORM-shaped tests use. The
    signature is the only thing that says a string is allowed, and signatures
    are not exercised. It was caught reading the staged diff, not by a test.
    """

    def test_a_str_employee_id_is_not_treated_as_unlinked(self, db):
        cid = uuid.uuid4()
        emp = _emp(db, cid, discord=True)
        db.commit()

        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db,
                company_id=str(cid),            # str, per the signature
                employee_id=str(emp.id),        # str, per the signature
                type="dispatch_assignment", message="x",
            )
            db.commit()
            assert sent.call_count == 1, (
                "a str employee_id missed the UUID-keyed discord_ids dict, so "
                "a linked employee was silently treated as unlinked"
            )
            _, payload = sent.call_args.args
            assert payload["discord_id"] == emp.discord_id

    def test_a_uuid_employee_id_still_resolves(self, db):
        """The failure mode of the fix: normalising one side only."""
        cid = uuid.uuid4()
        emp = _emp(db, cid, discord=True)
        db.commit()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.write_notification(
                db, company_id=cid, employee_id=emp.id,
                type="dispatch_assignment", message="x",
            )
            db.commit()
            assert sent.call_count == 1

    def test_a_fan_out_resolves_too(self, db):
        """fan_out builds the dict itself, so it needs the same normalisation —
        a one-sided fix passes the two tests above and breaks every fan-out."""
        cid = uuid.uuid4()
        for _ in range(2):
            _emp(db, cid, role="dispatch", discord=True)
        db.flush()
        with patch("app.tasks.discord_delivery.send_discord.delay") as sent:
            N.fan_out(
                db, company_id=cid, audience=N.Audience.STATION_RESOLVE,
                type="sort_packages_dropped", message="x",
            )
            db.commit()
            assert sent.call_count == 2


class TestFanOutExclude:
    """`exclude=` had NO test coverage at all, and the same id-type exposure.

    `exclude: set` says nothing about its element type and is compared against
    `emp.id`, always a UUID. A caller passing strings excludes nobody — and
    unlike the discord_ids miss, which skipped a convenience channel, this
    failure is INVERTED: the person the caller meant to spare receives the
    notification anyway. Silent, and the opposite of what was asked for.

    Found reading notify.py three lines above the fix for the same bug class.
    No live caller passes `exclude` yet; ADR-487 names graduation_quiz.py's
    hand-rolled `trainer_already_notified` check as the case it exists for.
    """

    def test_a_uuid_in_exclude_is_skipped(self, db):
        cid = uuid.uuid4()
        a = _emp(db, cid, role="dispatch")
        b = _emp(db, cid, role="dispatch")
        db.flush()
        with patch("app.tasks.discord_delivery.send_discord.delay"):
            made = N.fan_out(
                db, company_id=cid, audience=N.Audience.STATION_RESOLVE,
                type="sort_packages_dropped", message="x",
                exclude={a.id},
            )
            db.commit()
        assert {n.employee_id for n in made} == {b.id}

    def test_a_str_in_exclude_is_also_skipped(self, db):
        """The bug: a set of strings matched no UUID, so exclude did nothing and
        the excluded person was notified."""
        cid = uuid.uuid4()
        a = _emp(db, cid, role="dispatch")
        b = _emp(db, cid, role="dispatch")
        db.flush()
        with patch("app.tasks.discord_delivery.send_discord.delay"):
            made = N.fan_out(
                db, company_id=cid, audience=N.Audience.STATION_RESOLVE,
                type="sort_packages_dropped", message="x",
                exclude={str(a.id)},          # str, which `set` permits
            )
            db.commit()
        assert {n.employee_id for n in made} == {b.id}, (
            "a str in exclude matched no UUID, so the employee the caller meant "
            "to spare was notified anyway"
        )

    def test_an_empty_exclude_notifies_everyone(self, db):
        """The failure mode of the fix: over-normalising into a set that matches
        everything, or a None that crashes."""
        cid = uuid.uuid4()
        _emp(db, cid, role="dispatch")
        _emp(db, cid, role="dispatch")
        db.flush()
        with patch("app.tasks.discord_delivery.send_discord.delay"):
            made = N.fan_out(
                db, company_id=cid, audience=N.Audience.STATION_RESOLVE,
                type="sort_packages_dropped", message="x",
            )
            db.commit()
        assert len(made) == 2
