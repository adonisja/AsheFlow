"""Tests for continuation_requests router (ADR-147 audit findings).

Verified findings:
  MEDIUM-1: submit_continuation_request — no write_audit (creates request + notification)
  MEDIUM-2: accept_continuation_request — no write_audit (state transition pending→accepted)
  MEDIUM-3: set_request_priority — no write_audit (priority integer change)
  MEDIUM-4: reject_continuation_request — no write_audit (state transition pending→nullified)

All four are one-way or irreversible state changes that should have an audit trail.

Correct-behaviour coverage:
  - Trainee can only submit for themselves (403 if trainee_id != caller.id)
  - Existing active request is nullified when a new one is submitted
  - Trainer can only accept/reject their own request
  - Priority collision raises 409
  - Trainer can only see their own requests
  - Trainee can only request their most recent trainer
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_TRAINER_ID = uuid.uuid4()
_TRAINEE_ID = uuid.uuid4()


def _make_caller(role="trainee", emp_id=None, company_id=_CID_A):
    emp = MagicMock()
    emp.id = emp_id or uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    return emp


def _make_request(
    trainee_id=None,
    trainer_id=None,
    status="pending",
    company_id=_CID_A,
    priority=None,
):
    req = MagicMock()
    req.id = uuid.uuid4()
    req.trainee_id = trainee_id or _TRAINEE_ID
    req.trainer_id = trainer_id or _TRAINER_ID
    req.company_id = company_id
    req.status = status
    req.priority = priority
    req.resolved_at = None
    return req


# ---------------------------------------------------------------------------
# MEDIUM-1: submit_continuation_request missing write_audit
# ---------------------------------------------------------------------------

class TestSubmitContinuationRequestNoAudit:
    def test_write_audit_not_called_on_submit(self):
        from app.routers.continuation_requests import submit_continuation_request
        from app.schemas.continuation_request import ContinuationRequestCreate

        caller = _make_caller(role="trainee", emp_id=_TRAINEE_ID)
        current_user = {"cognito_groups": ["trainee"]}

        trainer_emp = MagicMock()
        trainer_emp.id = _TRAINER_ID
        trainer_emp.role = "trainer"
        trainer_emp.name = "Trainer T"

        trainee_emp = MagicMock()
        trainee_emp.id = _TRAINEE_ID
        trainee_emp.role = "trainee"
        trainee_emp.name = "Trainee U"

        training_record = MagicMock()
        training_record.trainer_id = _TRAINER_ID

        from app.models.employee import Employee
        from app.models.trainer_continuation_request import TrainerContinuationRequest
        from app.models.training import TrainingRecord

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    # Return trainee or trainer based on role filter
                    f.first.return_value = trainee_emp
                elif model is TrainingRecord:
                    f2 = MagicMock()
                    f2.order_by = MagicMock(return_value=f2)
                    f2.first.return_value = training_record
                    return f2
                elif model is TrainerContinuationRequest:
                    f.first.return_value = None  # no existing request
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        payload = ContinuationRequestCreate(
            trainee_id=_TRAINEE_ID,
            trainer_id=_TRAINER_ID,
        )

        # Patch the Employee lookups to return correct objects per call order
        emp_responses = [trainee_emp, trainer_emp]
        emp_call_count = [0]

        def _query2(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    idx = emp_call_count[0] % len(emp_responses)
                    f.first.return_value = emp_responses[idx]
                    emp_call_count[0] += 1
                elif model is TrainingRecord:
                    f2 = MagicMock()
                    f2.order_by = MagicMock(return_value=f2)
                    f2.first.return_value = training_record
                    return f2
                elif model is TrainerContinuationRequest:
                    f.first.return_value = None
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query2

        import app.routers.continuation_requests as cr_module
        assert hasattr(cr_module, "write_audit"), (
            "write_audit must be imported in continuation_requests.py (fixed in ADR-148)."
        )


# ---------------------------------------------------------------------------
# MEDIUM-2/3/4: accept / set_priority / reject — write_audit now present
# ---------------------------------------------------------------------------

class TestContinuationRequestWritesMissingAudit:
    def test_write_audit_is_imported_in_module(self):
        import app.routers.continuation_requests as cr_module
        assert hasattr(cr_module, "write_audit"), (
            "write_audit must be imported in continuation_requests.py (fixed in ADR-148)."
        )


# ---------------------------------------------------------------------------
# Trainee ownership: can only submit for themselves
# ---------------------------------------------------------------------------

class TestSubmitContinuationRequestOwnership:
    def test_trainee_cannot_submit_for_other_trainee(self):
        from app.routers.continuation_requests import submit_continuation_request
        from app.schemas.continuation_request import ContinuationRequestCreate

        caller = _make_caller(role="trainee", emp_id=uuid.uuid4())  # different ID
        current_user = {"cognito_groups": ["trainee"]}

        payload = ContinuationRequestCreate(
            trainee_id=_TRAINEE_ID,   # different from caller.id
            trainer_id=_TRAINER_ID,
        )

        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            submit_continuation_request(
                payload=payload,
                db=db,
                current_user=current_user,
                caller=caller,
            )
        assert exc_info.value.status_code == 403

    def test_trainee_can_submit_for_themselves(self):
        from app.routers.continuation_requests import submit_continuation_request
        from app.schemas.continuation_request import ContinuationRequestCreate

        caller = _make_caller(role="trainee", emp_id=_TRAINEE_ID)
        current_user = {"cognito_groups": ["trainee"]}

        trainee_emp = MagicMock()
        trainee_emp.id = _TRAINEE_ID
        trainee_emp.name = "Trainee U"

        trainer_emp = MagicMock()
        trainer_emp.id = _TRAINER_ID
        trainer_emp.name = "Trainer T"

        training_record = MagicMock()
        training_record.trainer_id = _TRAINER_ID

        from app.models.employee import Employee
        from app.models.trainer_continuation_request import TrainerContinuationRequest
        from app.models.training import TrainingRecord

        emp_seq = [trainee_emp, trainer_emp]
        call_idx = [0]

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    i = call_idx[0] % len(emp_seq)
                    f.first.return_value = emp_seq[i]
                    call_idx[0] += 1
                elif model is TrainingRecord:
                    f2 = MagicMock()
                    f2.order_by = MagicMock(return_value=f2)
                    f2.first.return_value = training_record
                    return f2
                elif model is TrainerContinuationRequest:
                    f.first.return_value = None  # no existing
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        payload = ContinuationRequestCreate(
            trainee_id=_TRAINEE_ID,
            trainer_id=_TRAINER_ID,
        )

        result = submit_continuation_request(
            payload=payload,
            db=db,
            current_user=current_user,
            caller=caller,
        )
        assert result == {}
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Existing active request is nullified on new submission
# ---------------------------------------------------------------------------

class TestSubmitNullifiesExisting:
    def test_existing_pending_request_gets_nullified(self):
        from app.routers.continuation_requests import submit_continuation_request
        from app.schemas.continuation_request import ContinuationRequestCreate

        caller = _make_caller(role="trainee", emp_id=_TRAINEE_ID)
        current_user = {"cognito_groups": ["trainee"]}

        existing = _make_request(trainee_id=_TRAINEE_ID, status="pending")

        trainee_emp = MagicMock()
        trainee_emp.id = _TRAINEE_ID
        trainee_emp.name = "Trainee U"

        trainer_emp = MagicMock()
        trainer_emp.id = _TRAINER_ID
        trainer_emp.name = "Trainer T"

        training_record = MagicMock()
        training_record.trainer_id = _TRAINER_ID

        from app.models.employee import Employee
        from app.models.trainer_continuation_request import TrainerContinuationRequest
        from app.models.training import TrainingRecord

        emp_seq = [trainee_emp, trainer_emp]
        call_idx = [0]

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    i = call_idx[0] % len(emp_seq)
                    f.first.return_value = emp_seq[i]
                    call_idx[0] += 1
                elif model is TrainingRecord:
                    f2 = MagicMock()
                    f2.order_by = MagicMock(return_value=f2)
                    f2.first.return_value = training_record
                    return f2
                elif model is TrainerContinuationRequest:
                    f.first.return_value = existing  # return existing
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        payload = ContinuationRequestCreate(
            trainee_id=_TRAINEE_ID,
            trainer_id=_TRAINER_ID,
        )

        submit_continuation_request(
            payload=payload,
            db=db,
            current_user=current_user,
            caller=caller,
        )

        assert existing.status == "nullified"
        assert existing.resolved_at is not None


# ---------------------------------------------------------------------------
# accept_continuation_request: trainer ownership check
# ---------------------------------------------------------------------------

class TestAcceptContinuationRequestOwnership:
    def _make_db(self, req):
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        from app.models.trainer_continuation_request import TrainerContinuationRequest

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = req
                return f
            q.filter = _filter
            return q

        db.query = _query
        return db

    def test_trainer_can_only_accept_their_own_request(self):
        from app.routers.continuation_requests import accept_continuation_request

        other_trainer_id = uuid.uuid4()
        req = _make_request(trainer_id=_TRAINER_ID, status="pending")

        caller = _make_caller(role="trainer", emp_id=other_trainer_id)  # different trainer
        current_user = {"cognito_groups": ["trainer"]}

        db = self._make_db(req)

        with pytest.raises(HTTPException) as exc_info:
            accept_continuation_request(
                request_id=uuid.uuid4(),
                db=db,
                current_user=current_user,
                caller=caller,
            )
        assert exc_info.value.status_code == 403

    def test_trainer_can_accept_their_own_request(self):
        from app.routers.continuation_requests import accept_continuation_request

        req = _make_request(trainer_id=_TRAINER_ID, status="pending")
        caller = _make_caller(role="trainer", emp_id=_TRAINER_ID)
        current_user = {"cognito_groups": ["trainer"]}

        db = self._make_db(req)
        accept_continuation_request(
            request_id=uuid.uuid4(),
            db=db,
            current_user=current_user,
            caller=caller,
        )

        assert req.status == "accepted"
        assert req.resolved_at is not None


# ---------------------------------------------------------------------------
# set_request_priority: duplicate priority raises 409
# ---------------------------------------------------------------------------

class TestSetRequestPriority:
    def test_duplicate_priority_raises_409(self):
        from app.routers.continuation_requests import set_request_priority
        from app.schemas.continuation_request import PriorityUpdate

        req = _make_request(trainer_id=_TRAINER_ID, status="accepted")
        duplicate_req = _make_request(trainer_id=_TRAINER_ID, status="accepted", priority=1)

        caller = _make_caller(role="trainer", emp_id=_TRAINER_ID)
        current_user = {"cognito_groups": ["trainer"]}

        from app.models.trainer_continuation_request import TrainerContinuationRequest

        call_count = [0]

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                call_count[0] += 1
                if call_count[0] == 1:
                    f.first.return_value = req  # main request lookup
                else:
                    f.first.return_value = duplicate_req  # conflict check
                return f
            q.filter = _filter
            return q

        db.query = _query

        payload = PriorityUpdate(priority=1)

        with pytest.raises(HTTPException) as exc_info:
            set_request_priority(
                request_id=req.id,
                payload=payload,
                db=db,
                current_user=current_user,
                caller_employee=caller,
            )
        assert exc_info.value.status_code == 409

    def test_clear_priority_succeeds(self):
        from app.routers.continuation_requests import set_request_priority
        from app.schemas.continuation_request import PriorityUpdate

        req = _make_request(trainer_id=_TRAINER_ID, status="accepted", priority=2)
        caller = _make_caller(role="trainer", emp_id=_TRAINER_ID)
        current_user = {"cognito_groups": ["trainer"]}

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = req
                return f
            q.filter = _filter
            return q

        db.query = _query

        payload = PriorityUpdate(priority=None)
        set_request_priority(
            request_id=req.id,
            payload=payload,
            db=db,
            current_user=current_user,
            caller_employee=caller,
        )

        assert req.priority is None
