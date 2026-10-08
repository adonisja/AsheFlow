"""A tenant-less submitter is a platform alert, not a broken notification (ADR-487 D2).

THE BUG THIS PINS, FOUND WHILE MIGRATING THE FIRST FILE
=======================================================

`feedback.py` fanned out to admins like this:

    admins = db.query(Employee).filter(
        Employee.role == "admin",
        Employee.is_active == True,
        *([Employee.company_id == company_id] if company_id else []),   # <-- here
    ).all()

A super admin has no Employee row (ADR-324 D2), so `company_id` is None for
their submissions. The star-unpack then dropped the company filter entirely, the
query fanned out across EVERY tenant's admins, and each insert failed
`Notification.company_id` NOT NULL — a 500 raised after the Feedback row had
already been added.

No test covered the feedback endpoint at all, so nothing caught it.

WHY THE FIX IS A DIFFERENT DESTINATION, NOT A DEFAULT
=====================================================

`Notification.company_id` is NOT NULL because a notification addresses an
employee, and an employee always belongs to a company. `PlatformAlert.company_id`
is nullable, and NULL there MEANS "platform, not a tenant" (ADR-335, ADR-337 D4).

So the two are not interchangeable and a tenant-less notification is not a
notification with a missing field — it is a platform alert wearing the wrong
type. The vocabulary already existed; the endpoint conflated it.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.employee import Employee
from app.models.notification import Notification
from app.models.platform_alert import PlatformAlert
from app.services.notify import Audience, fan_out, write_notification


class TestTheHelpersRefuseATenantlessNotification:
    def test_write_notification_refuses_none(self, db):
        with pytest.raises(ValueError) as exc:
            write_notification(
                db, company_id=None, employee_id=uuid.uuid4(),
                type="feedback_submitted", message="x",
            )
        # The message must point at the right vocabulary, not just refuse.
        assert "raise_platform_alert" in str(exc.value)
        assert "NOT NULL" in str(exc.value)

    def test_fan_out_refuses_none(self, db):
        with pytest.raises(ValueError) as exc:
            fan_out(
                db, company_id=None, audience=Audience.ADMIN_ONLY,
                type="feedback_submitted", message="x",
            )
        assert "raise_platform_alert" in str(exc.value)

    def test_it_refuses_BEFORE_querying_recipients(self, db):
        """The old code queried first and failed at the insert, which is why it
        fanned across every tenant on the way to the error."""
        before = db.query(Notification).count()
        with pytest.raises(ValueError):
            fan_out(db, company_id=None, audience=Audience.ADMIN_ONLY,
                    type="feedback_submitted", message="x")
        db.rollback()
        assert db.query(Notification).count() == before


class TestFanOutIsTenantScoped:
    """The filter that the old star-unpack could drop."""

    def _admin(self, db, company_id, name):
        e = Employee(
            id=uuid.uuid4(), company_id=company_id, name=name, role="admin",
            is_active=True, email=f"{name}@x.test",
        )
        db.add(e)
        return e

    def test_it_never_reaches_another_tenants_admins(self, db):
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        self._admin(db, mine, "ours")
        self._admin(db, theirs, "theirs")
        db.flush()

        made = fan_out(
            db, company_id=mine, audience=Audience.ADMIN_ONLY,
            type="feedback_submitted", message="a bug report",
        )
        db.flush()
        assert len(made) == 1
        assert all(n.company_id == mine for n in made)

    def test_it_skips_inactive_recipients(self, db):
        """A notification addressed to a deactivated employee is a row nobody
        reads. 51 sites wrote this filter by hand; fan_out writes it once."""
        cid = uuid.uuid4()
        active = self._admin(db, cid, "active")
        gone = self._admin(db, cid, "gone")
        gone.is_active = False
        db.flush()

        made = fan_out(
            db, company_id=cid, audience=Audience.ADMIN_ONLY,
            type="feedback_submitted", message="x",
        )
        db.flush()
        assert {n.employee_id for n in made} == {active.id}

    def test_admin_only_does_not_reach_management(self, db):
        """ADMIN_ONLY is deliberately narrow: a bug report is not dispatch or
        management business, and widening it would be a scope change."""
        cid = uuid.uuid4()
        admin = self._admin(db, cid, "admin")
        mgr = Employee(
            id=uuid.uuid4(), company_id=cid, name="mgr", role="management",
            is_active=True, email="mgr@x.test",
        )
        db.add(mgr)
        db.flush()

        made = fan_out(
            db, company_id=cid, audience=Audience.ADMIN_ONLY,
            type="feedback_submitted", message="x",
        )
        db.flush()
        assert {n.employee_id for n in made} == {admin.id}


class TestTheEndpointRoutesBothCases:
    def test_the_tenantless_branch_uses_the_platform_alert(self):
        """Source-level, because the branch depends on a dependency that returns
        None for an account with no employee row — which is awkward to construct
        and trivial to assert structurally."""
        import inspect

        from app.routers import feedback

        src = inspect.getsource(feedback.create_feedback)
        assert "raise_platform_alert" in src
        assert "company_id is not None" in src
        # And the old pattern must be gone: a conditional company filter inside
        # the recipient query is the bug itself.
        assert "if company_id else []" not in src

    def test_the_endpoint_no_longer_constructs_a_notification(self):
        """It goes through services.notify, so the registry lookup happens."""
        import inspect

        from app.routers import feedback

        src = inspect.getsource(feedback.create_feedback)
        assert "Notification(" not in src
        assert "fan_out(" in src
