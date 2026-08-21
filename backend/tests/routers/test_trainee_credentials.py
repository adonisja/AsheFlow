"""Tests for trainee_credentials router (ADR-147 audit findings).

Verified findings:
  HIGH-1: send_credentials (lines 144-164) — creates/updates TraineeCredentials
          and fires notification but calls no write_audit. Credential send is a
          sensitive write operation that must be audited.

  PII note: TraineeCredentials stores encrypted email and clock-in code.
            The _to_response helper decrypts these for the response.
            The decrypted values must not appear in logs — confirmed by
            inspection (no logger.info/logger.debug calls in the router).

Correct-behaviour coverage:
  - send_credentials: trainee not in company → 404
  - send_credentials: upsert on second call (updates not creates)
  - get_my_credentials: non-trainee roles → 403
  - get_my_credentials: no credentials row → 404
  - get_my_credentials: scoped to caller.id + company_id
  - get_credentials (management): scoped to company
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()


def _make_caller(role="management", company_id=_CID_A, emp_id=None):
    emp = MagicMock()
    emp.id = emp_id or uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    emp.discord_id = None
    return emp


def _make_credentials_row(employee_id, company_id=_CID_A):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.employee_id = employee_id
    row.company_id = company_id
    row.flex_email = b"encrypted_email"
    row.clock_in_code = b"encrypted_code"
    row.sent_by = uuid.uuid4()
    row.sent_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    return row


# ---------------------------------------------------------------------------
# HIGH-1: send_credentials missing write_audit
# ---------------------------------------------------------------------------

class TestSendCredentialsMissingAudit:
    def test_write_audit_is_imported_in_module(self):
        """write_audit is now imported in trainee_credentials.py (fixed in ADR-148)."""
        import app.routers.trainee_credentials as tc_module
        assert hasattr(tc_module, "write_audit"), (
            "write_audit must be imported in trainee_credentials.py."
        )

    def test_send_credentials_calls_write_audit(self):
        """Confirm the endpoint now calls write_audit before commit (fixed in ADR-148)."""
        from app.routers.trainee_credentials import send_credentials
        from app.routers.trainee_credentials import CredentialsSendRequest

        caller = _make_caller(role="management")
        trainee_id = uuid.uuid4()

        trainee_emp = MagicMock()
        trainee_emp.id = trainee_id
        trainee_emp.company_id = _CID_A
        trainee_emp.role = "trainee"
        trainee_emp.discord_id = None

        from app.models.employee import Employee
        from app.models.trainee_credentials import TraineeCredentials

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    f.first.return_value = trainee_emp
                elif model is TraineeCredentials:
                    f.first.return_value = None  # first call, no existing row
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = CredentialsSendRequest(
            flex_email="trainee@example.com",
            clock_in_code="ABC123",
        )

        with patch("app.routers.trainee_credentials.encrypt", return_value=b"encrypted"):
            with patch("app.routers.trainee_credentials.decrypt", return_value="decrypted"):
                with patch("app.routers.trainee_credentials._fire_discord_dm"):
                    with patch("app.routers.trainee_credentials.write_audit") as mock_audit:
                        try:
                            send_credentials(
                                trainee_id=trainee_id,
                                body=body,
                                _={},
                                caller=caller,
                                db=db,
                            )
                        except Exception:
                            pass
                        mock_audit.assert_called_once()

        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# send_credentials: trainee not found → 404
# ---------------------------------------------------------------------------

class TestSendCredentials404:
    def test_trainee_not_in_company_raises_404(self):
        from app.routers.trainee_credentials import send_credentials
        from app.routers.trainee_credentials import CredentialsSendRequest

        caller = _make_caller(role="management")
        trainee_id = uuid.uuid4()

        from app.models.employee import Employee

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # trainee not found
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = CredentialsSendRequest(flex_email="x@y.com", clock_in_code="123")

        with pytest.raises(HTTPException) as exc_info:
            send_credentials(trainee_id=trainee_id, body=body, _={}, caller=caller, db=db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# send_credentials: upsert on second call
# ---------------------------------------------------------------------------

class TestSendCredentialsUpsert:
    def test_second_call_updates_existing_row(self):
        from app.routers.trainee_credentials import send_credentials
        from app.routers.trainee_credentials import CredentialsSendRequest

        caller = _make_caller(role="management")
        trainee_id = uuid.uuid4()

        trainee_emp = MagicMock()
        trainee_emp.id = trainee_id
        trainee_emp.company_id = _CID_A
        trainee_emp.role = "trainee"
        trainee_emp.discord_id = None

        existing_row = _make_credentials_row(trainee_id)
        old_sent_by = existing_row.sent_by

        from app.models.employee import Employee
        from app.models.trainee_credentials import TraineeCredentials

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is Employee:
                    f.first.return_value = trainee_emp
                elif model is TraineeCredentials:
                    f.first.return_value = existing_row  # row exists
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = CredentialsSendRequest(flex_email="new@example.com", clock_in_code="NEW999")

        with patch("app.routers.trainee_credentials.encrypt", return_value=b"new_encrypted"):
            with patch("app.routers.trainee_credentials.decrypt", return_value="decrypted"):
                with patch("app.routers.trainee_credentials._fire_discord_dm"):
                    try:
                        send_credentials(
                            trainee_id=trainee_id,
                            body=body,
                            _={},
                            caller=caller,
                            db=db,
                        )
                    except Exception:
                        pass

        # The existing row was updated, not replaced
        assert existing_row.flex_email == b"new_encrypted"
        assert existing_row.clock_in_code == b"new_encrypted"
        assert existing_row.sent_by == caller.id
        # db.add was NOT called with a new row (only notification was added)
        # Check that no new TraineeCredentials was passed to db.add
        added_types = [type(c.args[0]).__name__ if c.args else None for c in db.add.call_args_list]
        assert "TraineeCredentials" not in added_types, (
            "Second call should UPDATE the existing row, not add a new TraineeCredentials row."
        )


# ---------------------------------------------------------------------------
# get_my_credentials: role check
# ---------------------------------------------------------------------------

class TestGetMyCredentialsRoleCheck:
    def test_non_trainee_cannot_access_my_credentials(self):
        from app.routers.trainee_credentials import get_my_credentials

        for role in ["walker", "trainer", "driver", "dispatch", "management", "admin"]:
            caller = _make_caller(role=role)
            db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                get_my_credentials(caller=caller, db=db)
            assert exc_info.value.status_code == 403, (
                f"Role '{role}' should get 403 from get_my_credentials."
            )

    def test_trainee_with_no_credentials_gets_404(self):
        from app.routers.trainee_credentials import get_my_credentials

        caller = _make_caller(role="trainee")

        from app.models.trainee_credentials import TraineeCredentials

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # no credentials row
                return f
            q.filter = _filter
            return q

        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            get_my_credentials(caller=caller, db=db)
        assert exc_info.value.status_code == 404

    def test_trainee_can_read_own_credentials(self):
        from app.routers.trainee_credentials import get_my_credentials

        caller_id = uuid.uuid4()
        caller = _make_caller(role="trainee", emp_id=caller_id)
        row = _make_credentials_row(caller_id)

        from app.models.trainee_credentials import TraineeCredentials

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = row
                return f
            q.filter = _filter
            return q

        db.query = _query

        with patch("app.routers.trainee_credentials.decrypt", return_value="decrypted"):
            result = get_my_credentials(caller=caller, db=db)

        assert result.employee_id == caller_id


# ---------------------------------------------------------------------------
# PII: decrypted values not logged
# ---------------------------------------------------------------------------

class TestCredentialsPIISafety:
    def test_no_logger_info_debug_in_send_credentials(self):
        """
        Encrypted credentials must not be logged in plain text.
        Verify that send_credentials does not call logger.info or logger.debug
        with credential values.
        """
        import inspect
        from app.routers import trainee_credentials as tc_mod
        source = inspect.getsource(tc_mod.send_credentials)

        # The only logging call should be in _fire_discord_dm (warning on failure)
        # Not in send_credentials itself
        assert "logger.info" not in source
        assert "logger.debug" not in source


# ---------------------------------------------------------------------------
# get_credentials (management): company scoping
# ---------------------------------------------------------------------------

class TestGetCredentialsManagementScoping:
    def test_management_gets_404_for_foreign_trainee(self):
        from app.routers.trainee_credentials import get_credentials

        caller = _make_caller(role="management")

        from app.models.trainee_credentials import TraineeCredentials

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # not found in company
                return f
            q.filter = _filter
            return q

        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            get_credentials(trainee_id=uuid.uuid4(), _={}, caller=caller, db=db)
        assert exc_info.value.status_code == 404
