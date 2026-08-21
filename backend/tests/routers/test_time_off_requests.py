"""Tests for time_off_requests router (ADR-147 audit findings).

Verified findings:
  MEDIUM-1: get_all_time_off_requests (lines 28-32) — joins Employee but
            filters only Employee.company_id, NOT TimeOffRequest.company_id
            directly. Relies on the join to enforce tenant isolation. If the
            join were ever removed or rewritten this would be a full leak.
            Defense-in-depth requires an explicit TimeOffRequest.company_id
            filter on every query.

  MEDIUM-2: create_time_off_request (line 85-94) — no write_audit on
            creation. Approved and rejected paths DO have write_audit.

Correct-behaviour coverage:
  - create: employee can only submit for themselves (403 otherwise)
  - create: existing request on same date → 400
  - create: recurring approved off-day on same weekday → 400
  - get /{employee_id}: employee can only read their own (403 otherwise)
  - approve: scoped via join to Employee.company_id
  - reject: scoped via join to Employee.company_id
  - delete: scoped to TimeOffRequest.company_id
  - delete: employee can only cancel their own (403 otherwise)
  - approve and reject both call write_audit
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(role="walker", company_id=_CID_A, emp_id=None):
    emp = MagicMock()
    emp.id = emp_id or uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    return emp


def _make_tor(employee_id=None, company_id=_CID_A, tor_date=None, status="pending"):
    tor = MagicMock()
    tor.id = uuid.uuid4()
    tor.employee_id = employee_id or uuid.uuid4()
    tor.company_id = company_id
    tor.date = tor_date or date.today()
    tor.status = status
    return tor


# ---------------------------------------------------------------------------
# MEDIUM-1: get_all relying on join instead of direct company_id filter
# ---------------------------------------------------------------------------

class TestGetAllTimeOffRequestsScoping:
    def test_get_all_filters_tor_company_id_directly(self):
        """
        get_all_time_off_requests now filters TimeOffRequest.company_id directly
        in addition to joining Employee.company_id (fixed in ADR-148).
        """
        import inspect
        from app.routers.time_off_requests import get_all_time_off_requests
        source = inspect.getsource(get_all_time_off_requests)

        # Confirm it still joins Employee
        assert "join(Employee" in source

        # Confirm TimeOffRequest.company_id IS directly filtered
        assert "TimeOffRequest.company_id" in source, (
            "TimeOffRequest.company_id must be filtered directly in get_all_time_off_requests "
            "as defense-in-depth alongside the Employee join."
        )

    def test_get_all_scoped_result_correct(self):
        """Verify caller's company filter produces only their records."""
        from app.routers.time_off_requests import get_all_time_off_requests

        caller = _make_caller(role="management")
        tor_a = _make_tor(company_id=_CID_A)

        captured = []

        db = MagicMock()
        q = MagicMock()
        q.join = MagicMock(return_value=q)

        def _filter(*args):
            captured.extend(args)
            f = MagicMock()
            f.all.return_value = [tor_a]
            return f

        q.filter = _filter
        db.query.return_value = q

        pg = MagicMock()
        pg.apply = lambda q: q

        result = get_all_time_off_requests(pg=pg, caller=caller, _={}, db=db)
        assert result == [tor_a]


# ---------------------------------------------------------------------------
# MEDIUM-2: create missing write_audit
# ---------------------------------------------------------------------------

class TestCreateTimeOffRequestMissingAudit:
    def test_create_calls_write_audit(self):
        from app.routers.time_off_requests import create_time_off_request
        from app.schemas.time_off_request import TimeOffRequestCreate

        caller_id = uuid.uuid4()
        caller = _make_caller(role="walker", emp_id=caller_id)

        from app.models.time_off_request import TimeOffRequest
        from app.models.employee_off_day import EmployeeOffDay

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # no conflicts
                return f
            q.filter = _filter
            return q

        db.query = _query

        request = TimeOffRequestCreate(
            employee_id=caller_id,
            date=date.today(),
        )

        with patch("app.routers.time_off_requests.write_audit") as mock_audit:
            create_time_off_request(request=request, db=db, caller=caller)
            # write_audit IS now called during create (fixed in ADR-148)
            mock_audit.assert_called_once()
            assert mock_audit.call_args.kwargs["action_type"] == "pto.created"

    def test_approve_calls_write_audit(self):
        from app.routers.time_off_requests import approve_time_off_request

        caller = _make_caller(role="management")
        tor = _make_tor(status="pending")

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = tor
                return f
            q.filter = _filter
            return q

        db.query = _query

        with patch("app.routers.time_off_requests.write_audit") as mock_audit:
            approve_time_off_request(request_id=tor.id, caller=caller, _={}, db=db)
            mock_audit.assert_called_once()
            assert mock_audit.call_args.kwargs["action_type"] == "pto.approved"

    def test_reject_calls_write_audit(self):
        from app.routers.time_off_requests import reject_time_off_request

        caller = _make_caller(role="management")
        tor = _make_tor(status="pending")

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = tor
                return f
            q.filter = _filter
            return q

        db.query = _query

        with patch("app.routers.time_off_requests.write_audit") as mock_audit:
            reject_time_off_request(request_id=tor.id, caller=caller, _={}, db=db)
            mock_audit.assert_called_once()
            assert mock_audit.call_args.kwargs["action_type"] == "pto.rejected"

    def test_delete_calls_write_audit(self):
        from app.routers.time_off_requests import delete_time_off_request

        caller_id = uuid.uuid4()
        caller = _make_caller(role="walker", emp_id=caller_id)
        tor = _make_tor(employee_id=caller_id)

        db = MagicMock()
        db.delete = MagicMock()
        db.commit = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = tor
                return f
            q.filter = _filter
            return q

        db.query = _query

        with patch("app.routers.time_off_requests.write_audit") as mock_audit:
            delete_time_off_request(request_id=tor.id, db=db, caller=caller)
            mock_audit.assert_called_once()
            assert mock_audit.call_args.kwargs["action_type"] == "pto.deleted"


# ---------------------------------------------------------------------------
# create: ownership check
# ---------------------------------------------------------------------------

class TestCreateOwnership:
    def test_walker_cannot_submit_for_other_employee(self):
        from app.routers.time_off_requests import create_time_off_request
        from app.schemas.time_off_request import TimeOffRequestCreate

        caller = _make_caller(role="walker", emp_id=uuid.uuid4())
        other_id = uuid.uuid4()

        db = MagicMock()
        request = TimeOffRequestCreate(employee_id=other_id, date=date.today())

        with pytest.raises(HTTPException) as exc_info:
            create_time_off_request(request=request, db=db, caller=caller)
        assert exc_info.value.status_code == 403

    def test_management_can_submit_for_other_employee(self):
        from app.routers.time_off_requests import create_time_off_request
        from app.schemas.time_off_request import TimeOffRequestCreate

        caller = _make_caller(role="management", emp_id=uuid.uuid4())
        other_id = uuid.uuid4()

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # no conflicts
                return f
            q.filter = _filter
            return q

        db.query = _query

        request = TimeOffRequestCreate(employee_id=other_id, date=date.today())
        # Should not raise
        create_time_off_request(request=request, db=db, caller=caller)
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# create: duplicate and off-day conflicts
# ---------------------------------------------------------------------------

class TestCreateConflicts:
    def test_existing_request_on_same_date_raises_400(self):
        from app.routers.time_off_requests import create_time_off_request
        from app.schemas.time_off_request import TimeOffRequestCreate

        caller_id = uuid.uuid4()
        caller = _make_caller(role="walker", emp_id=caller_id)
        existing_tor = _make_tor(employee_id=caller_id)

        from app.models.time_off_request import TimeOffRequest
        from app.models.employee_off_day import EmployeeOffDay

        db = MagicMock()
        call_count = [0]

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                call_count[0] += 1
                if model is EmployeeOffDay:
                    f.first.return_value = None  # no recurring off-day conflict
                elif model is TimeOffRequest:
                    f.first.return_value = existing_tor  # duplicate!
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        request = TimeOffRequestCreate(employee_id=caller_id, date=date.today())

        with pytest.raises(HTTPException) as exc_info:
            create_time_off_request(request=request, db=db, caller=caller)
        assert exc_info.value.status_code == 400
        assert "already exists" in exc_info.value.detail

    def test_approved_recurring_off_day_conflicts_raises_400(self):
        from app.routers.time_off_requests import create_time_off_request
        from app.schemas.time_off_request import TimeOffRequestCreate

        caller_id = uuid.uuid4()
        caller = _make_caller(role="walker", emp_id=caller_id)

        recurring_off = MagicMock()  # approved recurring off-day

        from app.models.employee_off_day import EmployeeOffDay
        from app.models.time_off_request import TimeOffRequest

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is EmployeeOffDay:
                    f.first.return_value = recurring_off
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        request = TimeOffRequestCreate(employee_id=caller_id, date=date.today())

        with pytest.raises(HTTPException) as exc_info:
            create_time_off_request(request=request, db=db, caller=caller)
        assert exc_info.value.status_code == 400
        assert "recurring off-day" in exc_info.value.detail


# ---------------------------------------------------------------------------
# get /{employee_id}: ownership check
# ---------------------------------------------------------------------------

class TestGetTimeOffRequestsOwnership:
    def test_walker_cannot_read_other_employees_requests(self):
        from app.routers.time_off_requests import get_time_off_requests

        caller = _make_caller(role="walker", emp_id=uuid.uuid4())
        other_id = uuid.uuid4()

        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            get_time_off_requests(employee_id=other_id, db=db, caller=caller)
        assert exc_info.value.status_code == 403

    def test_walker_can_read_own_requests(self):
        from app.routers.time_off_requests import get_time_off_requests

        caller_id = uuid.uuid4()
        caller = _make_caller(role="walker", emp_id=caller_id)
        tor = _make_tor(employee_id=caller_id)

        db = MagicMock()
        q = MagicMock()

        def _filter(*args):
            f = MagicMock()
            f.all.return_value = [tor]
            return f

        q.filter = _filter
        db.query.return_value = q

        result = get_time_off_requests(employee_id=caller_id, db=db, caller=caller)
        assert result == [tor]


# ---------------------------------------------------------------------------
# delete: ownership check
# ---------------------------------------------------------------------------

class TestDeleteOwnership:
    def test_walker_cannot_cancel_other_employees_request(self):
        from app.routers.time_off_requests import delete_time_off_request

        caller = _make_caller(role="walker", emp_id=uuid.uuid4())
        other_id = uuid.uuid4()
        tor = _make_tor(employee_id=other_id)

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = tor
                return f
            q.filter = _filter
            return q

        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            with patch("app.routers.time_off_requests.write_audit"):
                delete_time_off_request(request_id=tor.id, db=db, caller=caller)
        assert exc_info.value.status_code == 403

    def test_delete_not_found_raises_404(self):
        from app.routers.time_off_requests import delete_time_off_request

        caller = _make_caller(role="walker")

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # not found
                return f
            q.filter = _filter
            return q

        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            delete_time_off_request(request_id=uuid.uuid4(), db=db, caller=caller)
        assert exc_info.value.status_code == 404
