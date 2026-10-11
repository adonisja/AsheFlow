"""Acknowledgements are kept 1095 days, on FLSA §211 (ADR-494).

WHY THIS WINDOW
A `timecard_mismatch` acknowledgement is a wage-and-hour record: the employee
attests to their own hours and breaks. FLSA §211 requires employment records be
kept at least three years, which is the basis
`operational_record_retention_days` already cites in this codebase. That is the
longest-justified of the five interruptive types, so it sets the window for all
of them — one clock and one cited statute, rather than a per-type map that
drifts from the registry.

WHY A PURGE AT ALL
The row survives its notification by design (the D8 fix), and nothing else
bounds it. Unbounded is defensible for evidence and is not obviously right
forever; three years with a statute behind it is.

THE FAILURE MODE THIS GUARDS
This task is the LAST thing holding the row — no soft delete, no archive. The
two ways it goes wrong are deleting too early (evidence gone before a dispute
window closes) and deleting nothing forever (a filter that matches no rows and
reports success). Both are covered below.
"""
from __future__ import annotations

import ast
import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings


class TestTheWindowHasAStatedBasis:
    """A retention number without a basis is a guess that outlives its author."""

    def test_it_is_1095_days(self):
        assert settings.acknowledgement_retention_days == 1095, (
            "the acknowledgement window changed. 1095 is FLSA §211's three years "
            "for employment records — if this moves, the new number needs its own "
            "cited basis, not a round figure."
        )

    def test_it_matches_the_operational_window_it_borrows_from(self):
        """Same statute, so the same number. If one moves, both should be read."""
        assert (settings.acknowledgement_retention_days
                == settings.operational_record_retention_days), (
            "the acknowledgement and operational windows have diverged. Both cite "
            "FLSA §211; if that is still true they should agree, and if one has a "
            "different basis now it needs to say so."
        )

    def test_zero_disables_rather_than_purging_everything(self):
        """`0` must mean OFF, not "cutoff = now".

        A retention setting where 0 deletes everything is the worst possible
        misreading of a disable flag, and it is one `<=` away.
        """
        src = inspect.getsource(_task())
        assert "retention_days <= 0" in src
        assert "skipped" in src


def _task():
    from app.tasks.cleanup import purge_expired_acknowledgements
    return purge_expired_acknowledgements


class TestItCountsFromTheAcknowledgement:
    """NOT from the notification, which is ~3 years gone by then."""

    def test_the_filter_is_on_acknowledged_at(self):
        """Parsed, not grepped: the docstring names several columns."""
        tree = ast.parse(inspect.getsource(_task()).lstrip())
        attrs = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "acknowledged_at" in attrs, (
            "the purge no longer filters on acknowledged_at — the only other "
            "date available is the notification's, and the notification has been "
            "deleted for three years by the time this runs"
        )

    def test_it_does_not_join_to_notifications(self):
        """A join here matches nothing and deletes nothing, forever, silently.

        `prune_notifications` removes the notification after 3 days and the FK is
        SET NULL, so every row this task sees has notification_id IS NULL. A
        join would report success having done nothing — the shape of bug that
        survives for years because its metric looks healthy.
        """
        tree = ast.parse(inspect.getsource(_task()).lstrip())
        joins = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "join"
        ]
        assert joins == [], (
            f"the purge joins another table at line(s) {[j.lineno for j in joins]}. "
            f"Every row it sees has notification_id IS NULL, so a join deletes "
            f"nothing and logs a successful run."
        )


class TestItDeletesTheRightRows:
    """Against real rows. A purge verified only by reading is not verified."""

    @pytest.fixture
    def db(self):
        from app.database import SessionLocal
        s = SessionLocal()
        yield s
        s.close()

    def _ack(self, db, company_id, employee_id, *, age_days: int):
        from app.models.role_guide import NotificationAcknowledgement
        row = NotificationAcknowledgement(
            notification_id=None,          # as it will be: the notification is long gone
            notification_type="timecard_mismatch",
            message_snapshot="Action required: hours do not match.",
            employee_id=employee_id,
            company_id=company_id,
            acknowledged_at=datetime.now(timezone.utc) - timedelta(days=age_days),
            action="confirmed",
            shown_as="gate",
        )
        db.add(row)
        db.flush()
        return row.id

    def test_older_than_the_window_goes_and_newer_stays(self, db):
        from app.models.employee import Employee
        from app.models.role_guide import NotificationAcknowledgement
        from app.tasks.cleanup import purge_expired_acknowledgements

        emp = db.query(Employee).first()
        if emp is None:
            pytest.skip("no employee row in this database to attach an ack to")

        # One day past, one day short, and one exactly inside the boundary.
        old = self._ack(db, emp.company_id, emp.id, age_days=1096)
        new = self._ack(db, emp.company_id, emp.id, age_days=1094)
        edge = self._ack(db, emp.company_id, emp.id, age_days=1)
        db.commit()

        try:
            result = purge_expired_acknowledgements()
            assert result.get("skipped") is not True
            assert result["days"] == 1095

            db.expire_all()
            q = db.query(NotificationAcknowledgement.id)
            assert q.filter_by(id=old).first() is None, (
                "a 1096-day-old acknowledgement survived the 1095-day purge"
            )
            assert q.filter_by(id=new).first() is not None, (
                "a 1094-day-old acknowledgement was deleted by a 1095-day purge "
                "— the boundary is off by at least a day, and this is evidence"
            )
            assert q.filter_by(id=edge).first() is not None, (
                "a 1-day-old acknowledgement was deleted. The cutoff is inverted."
            )
        finally:
            for ack_id in (old, new, edge):
                db.query(NotificationAcknowledgement).filter_by(
                    id=ack_id).delete(synchronize_session=False)
            db.commit()

    def test_it_reports_what_it_deleted(self, db):
        """Returning a count, not None.

        A destructive job whose return value does not say how much it destroyed
        gives an operator nothing to notice an anomaly with.
        """
        from app.tasks.cleanup import purge_expired_acknowledgements

        result = purge_expired_acknowledgements()
        assert "deleted" in result and isinstance(result["deleted"], int)
        assert "cutoff" in result


class TestItIsScheduled:
    """A task with no beat entry never runs, and nothing reports that."""

    def test_the_beat_entry_exists(self):
        from app.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        entries = [
            v for v in schedule.values()
            if v["task"] == "app.tasks.cleanup.purge_expired_acknowledgements"
        ]
        assert len(entries) == 1, (
            f"{len(entries)} beat entries for the acknowledgement purge — a task "
            f"with none never runs; two run it twice"
        )

    def test_it_does_not_share_a_minute_with_the_operational_purge(self):
        """Both run on the 1st, so a shared minute collides monthly — exactly
        the case the 3:31 entry's own comment records as having been missed by a
        daily-only collision scan."""
        from app.celery_app import celery_app

        def slot(task_name):
            for v in celery_app.conf.beat_schedule.values():
                if v["task"] == task_name:
                    c = v["schedule"]
                    return (c.hour, c.minute, c.day_of_month)
            return None

        ack = slot("app.tasks.cleanup.purge_expired_acknowledgements")
        ops = slot("app.tasks.cleanup.purge_expired_operational_records")
        assert ack is not None and ops is not None
        assert (ack[0], ack[1]) != (ops[0], ops[1]), (
            f"the two purges share {ack[0]}:{ack[1]} and both run on the 1st"
        )
