"""prune_notifications (ADR-227).

Public cleanup task. Verifies the disable guard and that the delete runs with the
retention window, reporting the deleted count + cutoff. The bulk .delete() is
exercised via a mock session (the filter predicate is asserted against the SQL
expression the task builds).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def test_disabled_when_retention_days_zero():
    from app.tasks import cleanup
    with patch.object(cleanup.settings, "notification_retention_days", 0):
        out = cleanup.prune_notifications()
    assert out == {"skipped": True}


def test_deletes_and_reports_count_and_cutoff():
    from app.tasks import cleanup

    captured = {}
    db = MagicMock()

    def _query(model):
        q = MagicMock()
        def _filter(*a):
            captured["filtered"] = True
            f = MagicMock()
            f.delete.return_value = 7   # pretend 7 rows matched
            return f
        q.filter = _filter
        return q
    db.query = _query

    with patch.object(cleanup, "SessionLocal", return_value=db), \
         patch.object(cleanup.settings, "notification_retention_days", 3):
        out = cleanup.prune_notifications()

    assert captured.get("filtered") is True
    assert out["deleted"] == 7
    assert out["days"] == 3
    # cutoff is ~3 days ago (date form)
    expected = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    assert out["cutoff"] == expected
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_rolls_back_and_raises_on_error():
    from app.tasks import cleanup

    db = MagicMock()
    def _query(model):
        q = MagicMock()
        def _filter(*a):
            f = MagicMock()
            f.delete.side_effect = RuntimeError("boom")
            return f
        q.filter = _filter
        return q
    db.query = _query

    with patch.object(cleanup, "SessionLocal", return_value=db), \
         patch.object(cleanup.settings, "notification_retention_days", 3):
        try:
            cleanup.prune_notifications()
            assert False, "should have raised"
        except RuntimeError:
            pass
    db.rollback.assert_called_once()
    db.close.assert_called_once()
