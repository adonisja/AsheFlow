"""ADR-445 D3/D5: what a verified bounce actually does to the data.

The signature tests cover the door. These cover the room: which rows get
flagged, which do not, and who hears about it.
"""
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.models.employee import Employee
from app.models.notification import Notification
from app.routers import sns_events as S
from tests.conftest import SEED_COMPANY_ID


def _emp(db, *, name, email, company_id=SEED_COMPANY_ID, role="walker", active=True):
    e = Employee(
        id=uuid.uuid4(), company_id=company_id, name=name, email=email,
        role=role, is_active=active, account_status="pending_verification",
    )
    db.add(e)
    db.flush()
    return e


def _bounce(address, kind="Permanent"):
    return {"eventType": "Bounce", "bounce": {
        "bounceType": kind,
        "bouncedRecipients": [{"emailAddress": address}]}}


def _complaint(address):
    return {"eventType": "Complaint", "complaint": {
        "complainedRecipients": [{"emailAddress": address}]}}


class TestWhichRowsAreFlagged:
    def test_a_hard_bounce_flags_the_employee(self, db):
        e = _emp(db, name="Dana", email="dana@example.com")
        now = datetime.now(timezone.utc)
        assert S._flag(db, "dana@example.com", "Permanent", now) == 1
        db.flush()
        assert e.email_bounced_at == now
        assert e.email_bounce_type == "Permanent"

    def test_a_transient_bounce_flags_nothing(self, db):
        """A full mailbox is not a bad address.

        AWS does not suppress it, and flagging it would train admins to ignore
        the flag — so the recipient extractor must drop it before any write.
        """
        _emp(db, name="Dana", email="dana@example.com")
        addresses, kind = S._recipients(_bounce("dana@example.com", "Transient"))
        assert addresses == [] and kind is None

    def test_a_complaint_is_recorded_with_its_own_type(self, db):
        """Same operational consequence, different remedy.

        AWS suppresses either way, so we must stop sending — but a typo gets
        corrected and a complaint gets a conversation.
        """
        e = _emp(db, name="Dana", email="dana@example.com")
        addresses, kind = S._recipients(_complaint("dana@example.com"))
        assert addresses == ["dana@example.com"] and kind == "Complaint"
        S._flag(db, "dana@example.com", kind, datetime.now(timezone.utc))
        db.flush()
        assert e.email_bounce_type == "Complaint"

    def test_an_unknown_address_flags_nothing_and_does_not_raise(self, db):
        """SES bounces for mail we did not send about an employee we do not have."""
        assert S._flag(db, "stranger@example.com", "Permanent",
                       datetime.now(timezone.utc)) == 0


class TestTheSameAddressAtTwoCompanies:
    """Email is unique per company, NOT globally (uq_employees_company_email).

    Flagging only the first match is the cross-tenant bug hiding in this
    feature: the second company's admin keeps resending into a dead mailbox
    with no indication why.
    """

    def test_both_rows_are_flagged(self, db):
        other_company = uuid.uuid4()
        a = _emp(db, name="Dana", email="dana@example.com")
        b = _emp(db, name="Dana", email="dana@example.com", company_id=other_company)

        assert S._flag(db, "dana@example.com", "Permanent",
                       datetime.now(timezone.utc)) == 2
        db.flush()
        assert a.email_bounced_at is not None
        assert b.email_bounced_at is not None

    def test_each_company_is_notified_separately(self, db):
        other_company = uuid.uuid4()
        mgr_a = _emp(db, name="Mgr A", email="a@x.com", role="management")
        mgr_b = _emp(db, name="Mgr B", email="b@x.com",
                     company_id=other_company, role="management")
        _emp(db, name="Dana", email="dana@example.com")
        _emp(db, name="Dana", email="dana@example.com", company_id=other_company)

        S._flag(db, "dana@example.com", "Permanent", datetime.now(timezone.utc))
        db.flush()

        notes = db.query(Notification).filter(Notification.type == "email_bounced").all()
        recipients = {n.employee_id for n in notes}
        assert mgr_a.id in recipients and mgr_b.id in recipients
        # and no notification crossed a company boundary
        by_company = {n.employee_id: n.company_id for n in notes}
        assert by_company[mgr_a.id] == SEED_COMPANY_ID
        assert by_company[mgr_b.id] == other_company


class TestWhoHearsAboutIt:
    def test_management_and_admin_are_notified(self, db):
        mgr = _emp(db, name="Mgr", email="m@x.com", role="management")
        adm = _emp(db, name="Adm", email="ad@x.com", role="admin")
        _emp(db, name="Dana", email="dana@example.com")

        S._flag(db, "dana@example.com", "Permanent", datetime.now(timezone.utc))
        db.flush()
        got = {n.employee_id for n in db.query(Notification).all()}
        assert {mgr.id, adm.id} <= got

    def test_a_walker_is_not_notified(self, db):
        walker = _emp(db, name="Walker", email="w@x.com", role="walker")
        _emp(db, name="Dana", email="dana@example.com")
        S._flag(db, "dana@example.com", "Permanent", datetime.now(timezone.utc))
        db.flush()
        got = {n.employee_id for n in db.query(Notification).all()}
        assert walker.id not in got

    def test_the_bounced_employee_is_never_notified(self, db):
        """Their email does not work — that is the entire point.

        And an in-app notification for an account they have never signed into
        is unreachable by construction.
        """
        dana = _emp(db, name="Dana", email="dana@example.com", role="management")
        S._flag(db, "dana@example.com", "Permanent", datetime.now(timezone.utc))
        db.flush()
        got = {n.employee_id for n in db.query(Notification).all()}
        assert dana.id not in got

    def test_the_notification_never_contains_the_address(self, db):
        """Dimension 7 at the sink.

        The admin can see the address on the employee record; a notification
        list is a wider audience than that record.
        """
        _emp(db, name="Mgr", email="m@x.com", role="management")
        _emp(db, name="Dana", email="dana@example.com")
        S._flag(db, "dana@example.com", "Permanent", datetime.now(timezone.utc))
        db.flush()
        for note in db.query(Notification).all():
            assert "dana@example.com" not in note.message
            assert "Dana" in note.message


class TestIdempotence:
    """SNS guarantees AT-LEAST-once delivery, so the same bounce arrives twice."""

    def test_the_same_event_does_not_notify_twice(self, db):
        _emp(db, name="Mgr", email="m@x.com", role="management")
        _emp(db, name="Dana", email="dana@example.com")
        now = datetime.now(timezone.utc)

        assert S._flag(db, "dana@example.com", "Permanent", now) == 1
        db.flush()
        assert S._flag(db, "dana@example.com", "Permanent", now) == 0
        db.flush()
        assert db.query(Notification).count() == 1

    def test_a_later_bounce_does_record_again(self, db):
        """A second, genuinely new failure is news."""
        _emp(db, name="Mgr", email="m@x.com", role="management")
        _emp(db, name="Dana", email="dana@example.com")
        S._flag(db, "dana@example.com", "Permanent", datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.flush()
        assert S._flag(db, "dana@example.com", "Permanent",
                       datetime(2026, 9, 19, tzinfo=timezone.utc)) == 1


class TestTheEventShape:
    def test_several_recipients_in_one_event_are_all_returned(self):
        payload = {"eventType": "Bounce", "bounce": {
            "bounceType": "Permanent",
            "bouncedRecipients": [{"emailAddress": "a@x.com"},
                                  {"emailAddress": "b@x.com"}]}}
        addresses, kind = S._recipients(payload)
        assert addresses == ["a@x.com", "b@x.com"] and kind == "Permanent"

    def test_a_delivery_event_is_ignored(self):
        assert S._recipients({"eventType": "Delivery"}) == ([], None)

    def test_the_legacy_notificationType_key_is_understood(self):
        """SES sends `notificationType` on some paths and `eventType` on others."""
        payload = {"notificationType": "Bounce", "bounce": {
            "bounceType": "Permanent",
            "bouncedRecipients": [{"emailAddress": "a@x.com"}]}}
        assert S._recipients(payload) == (["a@x.com"], "Permanent")


class TestResendIsBlockedAfterABounce:
    """ADR-445 D8. The cross-system half of this feature.

    A bounce that only paints a badge is decoration. The point is that the
    system stops doing the thing that cannot work.
    """

    def test_the_invite_endpoint_refuses_a_bounced_address(self):
        """Resending to a suppressed address LOOKS like it worked.

        AWS suppresses the address account-wide, SES accepts the call, the
        message is dropped -- and the admin waits for a second reply that
        cannot come.
        """
        import ast
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1] / "app/routers/registration.py"
        tree = ast.parse(src.read_text())
        # POST /invite, which doubles as the resend ("Can be called multiple
        # times to re-send if the previous link expired").
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "send_invite")
        reads = {
            n.attr for n in ast.walk(fn)
            if isinstance(n, ast.Attribute) and n.attr == "email_bounced_at"
        }
        assert "email_bounced_at" in reads, (
            "send_invite does not check email_bounced_at — it would send into "
            "a suppressed address and report success (ADR-445 D8)."
        )

    def test_resend_credentials_deliberately_does_not(self):
        """The asymmetry is the decision, so it is pinned.

        resend_credentials returns the password when the send fails (ADR-442
        D2), making it the operator's way IN to an account whose address is
        dead. Blocking it would remove the only remaining route.
        """
        import ast
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1] / "app/routers/registration.py"
        tree = ast.parse(src.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "resend_credentials")
        raises_on_bounce = any(
            isinstance(n, ast.Attribute) and n.attr == "email_bounced_at"
            for n in ast.walk(fn)
        )
        assert not raises_on_bounce, (
            "resend_credentials now gates on email_bounced_at. If that is "
            "intended, ADR-445 D8 must change first — it is currently the only "
            "way to reach an account whose address is dead."
        )
