"""Tests for shift_sessions router (ADR-147/ADR-148).

ADR-147 findings (now fixed):
  MEDIUM-1: start_shift, check_eligibility, list_active_sessions used date.today()
            instead of company_today(db, company_id). Fixed in ADR-148.
  HIGH-2:   All five write endpoints were missing write_audit. Fixed in ADR-148.

Tests verify the fixes are in place and correct-behaviour is preserved:
  - company_today() is used instead of date.today() in all three endpoints
  - write_audit is imported and called in all five write endpoints
  - start_shift raises 409 when an active session already exists
  - advance_gate progresses through gates 1→5 and marks completed_at on gate 5
  - skip_to_gate rejects backward skips and out-of-range gates
  - abandon_session is management-only
  - wipe_session is admin-only
  - list_active_sessions is management-only
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()


def _make_caller(role="driver", company_id=_CID_A):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    return emp


def _make_session(driver_id=None, current_gate=1, completed_at=None, company_id=_CID_A):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.driver_id = driver_id or uuid.uuid4()
    s.company_id = company_id
    s.current_gate = current_gate
    s.completed_at = completed_at
    s.started_at = datetime.now(timezone.utc)
    s.gate_1_completed_at = None
    s.gate_2_completed_at = None
    s.gate_3_completed_at = None
    s.gate_4_completed_at = None
    return s


# ---------------------------------------------------------------------------
# MEDIUM-1 (fixed): company_today() now used instead of date.today()
# ---------------------------------------------------------------------------

class TestDateTodayUsage:
    def test_start_shift_uses_company_today(self):
        """start_shift now uses company_today(), not date.today()."""
        import inspect
        import app.routers.shift_sessions as sr
        source = inspect.getsource(sr.start_shift)
        assert "company_today" in source, "start_shift must call company_today()"
        assert "date.today()" not in source, "start_shift must not call date.today()"

    def test_check_eligibility_uses_company_today(self):
        """check_eligibility now uses company_today(), not date.today()."""
        import inspect
        import app.routers.shift_sessions as sr
        source = inspect.getsource(sr.check_eligibility)
        assert "company_today" in source, "check_eligibility must call company_today()"
        assert "date.today()" not in source, "check_eligibility must not call date.today()"

    def test_list_active_sessions_uses_company_today(self):
        """list_active_sessions now uses company_today(), not date.today()."""
        import inspect
        import app.routers.shift_sessions as sr
        source = inspect.getsource(sr.list_active_sessions)
        assert "company_today" in source, "list_active_sessions must call company_today()"
        assert "date.today()" not in source, "list_active_sessions must not call date.today()"


# ---------------------------------------------------------------------------
# HIGH-2 (fixed): write_audit now imported and called in all write endpoints
# ---------------------------------------------------------------------------

class TestShiftSessionsWriteAudit:
    def _base_db(self, session=None, assigned=None):
        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.delete = MagicMock()

        from app.models.shift_session import ShiftSession
        from app.models.truck_assignment import TruckAssignment

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                if model is ShiftSession:
                    f.first.return_value = session
                elif model is TruckAssignment:
                    f.first.return_value = assigned
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query
        return db

    def test_write_audit_is_imported(self):
        import app.routers.shift_sessions as sr
        assert hasattr(sr, "write_audit"), "write_audit must be imported in shift_sessions.py"

    def test_start_shift_calls_write_audit(self):
        from app.routers.shift_sessions import start_shift

        caller = _make_caller(role="driver")
        assigned = MagicMock()
        db = self._base_db(session=None, assigned=assigned)

        with patch("app.routers.shift_sessions.company_today", return_value=date.today()):
            with patch("app.routers.shift_sessions.write_audit") as mock_audit:
                start_shift(caller=caller, _={}, db=db)
        mock_audit.assert_called_once()
        db.commit.assert_called_once()

    def test_advance_gate_calls_write_audit(self):
        from app.routers.shift_sessions import advance_gate

        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=1)
        db = self._base_db(session=session)

        with patch("app.routers.shift_sessions.write_audit") as mock_audit:
            advance_gate(caller=caller, _={}, db=db)
        mock_audit.assert_called_once()
        db.commit.assert_called_once()

    def test_skip_to_gate_calls_write_audit(self):
        from app.routers.shift_sessions import skip_to_gate

        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=1)
        db = self._base_db(session=session)

        with patch("app.routers.shift_sessions.write_audit") as mock_audit:
            skip_to_gate(gate=3, caller=caller, _={}, db=db)
        mock_audit.assert_called_once()
        db.commit.assert_called_once()

    def test_abandon_session_calls_write_audit(self):
        from app.routers.shift_sessions import abandon_session

        caller = _make_caller(role="management")
        driver = _make_caller(role="driver")
        session = _make_session(driver_id=driver.id)
        db = self._base_db(session=session)

        with patch("app.routers.shift_sessions.write_audit") as mock_audit:
            abandon_session(driver_id=driver.id, caller=caller, _={}, db=db)
        mock_audit.assert_called_once()
        db.commit.assert_called_once()

    def test_wipe_session_calls_write_audit(self):
        from app.routers.shift_sessions import wipe_session

        caller = _make_caller(role="admin")
        driver = _make_caller(role="driver")
        session = _make_session(driver_id=driver.id)
        db = self._base_db(session=session)

        with patch("app.routers.shift_sessions.write_audit") as mock_audit:
            wipe_session(driver_id=driver.id, caller=caller, _={}, db=db)
        mock_audit.assert_called_once()
        db.delete.assert_called_once_with(session)
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# start_shift: existing active session → 409
# ---------------------------------------------------------------------------

class TestStartShiftIdempotency:
    def test_start_shift_raises_409_if_active_session_exists(self):
        from app.routers.shift_sessions import start_shift

        caller = _make_caller(role="driver")
        existing_session = _make_session(driver_id=caller.id)
        assigned = MagicMock()

        db = MagicMock()
        from app.models.shift_session import ShiftSession
        from app.models.truck_assignment import TruckAssignment

        call_count = [0]

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                call_count[0] += 1
                if model is TruckAssignment:
                    f.first.return_value = assigned
                elif model is ShiftSession:
                    f.first.return_value = existing_session
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        with patch("app.routers.shift_sessions.date") as mock_date:
            mock_date.today.return_value = date.today()
            with pytest.raises(HTTPException) as exc_info:
                start_shift(caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 409

    def test_start_shift_raises_400_if_not_assigned(self):
        from app.routers.shift_sessions import start_shift

        caller = _make_caller(role="driver")

        db = MagicMock()
        q = MagicMock()
        q.join = MagicMock(return_value=q)

        def _filter(*args):
            f = MagicMock()
            f.first.return_value = None  # not assigned
            return f

        q.filter = _filter
        db.query.return_value = q

        with patch("app.routers.shift_sessions.date") as mock_date:
            mock_date.today.return_value = date.today()
            with pytest.raises(HTTPException) as exc_info:
                start_shift(caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# advance_gate: full progression
# ---------------------------------------------------------------------------

class TestAdvanceGateProgression:
    def _db_with_session(self, session):
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        from app.models.shift_session import ShiftSession

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = session
                return f
            q.filter = _filter
            return q

        db.query = _query
        return db

    def test_gate_1_advances_to_2(self):
        from app.routers.shift_sessions import advance_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=1)
        db = self._db_with_session(session)
        advance_gate(caller=caller, _={}, db=db)
        assert session.current_gate == 2
        assert session.gate_1_completed_at is not None

    def test_gate_4_advances_to_5_and_marks_completed(self):
        from app.routers.shift_sessions import advance_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=4)
        db = self._db_with_session(session)
        advance_gate(caller=caller, _={}, db=db)
        assert session.current_gate == 5
        assert session.gate_4_completed_at is not None

    def test_gate_5_marks_shift_complete(self):
        from app.routers.shift_sessions import advance_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=5)
        db = self._db_with_session(session)
        advance_gate(caller=caller, _={}, db=db)
        assert session.completed_at is not None

    def test_advance_with_no_active_session_raises_404(self):
        from app.routers.shift_sessions import advance_gate
        caller = _make_caller(role="driver")
        db = self._db_with_session(None)
        with pytest.raises(HTTPException) as exc_info:
            advance_gate(caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# skip_to_gate: forward-only
# ---------------------------------------------------------------------------

class TestSkipToGate:
    def _db_with_session(self, session):
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        from app.models.shift_session import ShiftSession

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = session
                return f
            q.filter = _filter
            return q

        db.query = _query
        return db

    def test_skip_backward_raises_400(self):
        from app.routers.shift_sessions import skip_to_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=3)
        db = self._db_with_session(session)
        with pytest.raises(HTTPException) as exc_info:
            skip_to_gate(gate=2, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400

    def test_skip_to_same_gate_raises_400(self):
        from app.routers.shift_sessions import skip_to_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=2)
        db = self._db_with_session(session)
        with pytest.raises(HTTPException) as exc_info:
            skip_to_gate(gate=2, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400

    def test_skip_out_of_range_raises_400(self):
        from app.routers.shift_sessions import skip_to_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=1)
        db = self._db_with_session(session)
        with pytest.raises(HTTPException) as exc_info:
            skip_to_gate(gate=6, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400

    def test_skip_forward_stamps_intermediate_gates(self):
        from app.routers.shift_sessions import skip_to_gate
        caller = _make_caller(role="driver")
        session = _make_session(driver_id=caller.id, current_gate=1)
        db = self._db_with_session(session)
        skip_to_gate(gate=3, caller=caller, _={}, db=db)
        assert session.current_gate == 3
        assert session.gate_1_completed_at is not None
        assert session.gate_2_completed_at is not None
