"""ADR-491 — trainee credentials are a handoff, not a record.

Management issues temporary Flex credentials; the trainee changes both on first
sign-in. AsheFlow keeps the values only until the trainee confirms, or 14 days
after sending, and management never reads them back.

Real database rows throughout: the point is which rows hold a secret afterwards,
and a mock cannot answer that.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.models.trainee_credentials import TraineeCredentials
from app.routers import trainee_credentials as tc
from app.tasks import cleanup
from tests.conftest import make_employee, sqlite_mirror_with_defaults


@pytest.fixture(autouse=True)
def _credential_table(db):
    sqlite_mirror_with_defaults(TraineeCredentials.__table__).create(db.get_bind())


@pytest.fixture
def people(db):
    return make_employee(db, role="management", name="Mgr"), make_employee(db, role="trainee", name="Trainee")


def _send(db, mgr, trainee):
    with patch.object(tc, "send_discord"):
        return tc.send_credentials(
            trainee_id=trainee.id,
            body=tc.CredentialsSendRequest(flex_email="temp@example.com", clock_in_code="1234"),
            _={}, caller=mgr, db=db,
        )


def _row(db, trainee):
    db.expire_all()
    return db.query(TraineeCredentials).filter_by(employee_id=trainee.id).one()


class TestManagementNeverReadsTheValues:
    def test_the_status_schema_has_no_secret_fields(self):
        """Structural: there is no field to leak into. A future edit that adds
        one has to delete this test to do it."""
        assert "flex_email" not in tc.CredentialsStatus.model_fields
        assert "clock_in_code" not in tc.CredentialsStatus.model_fields

    def test_send_returns_status_only(self, db, people):
        mgr, trainee = people
        out = _send(db, mgr, trainee)
        assert isinstance(out, tc.CredentialsStatus) and not isinstance(out, tc.MyCredentials)
        assert out.has_credentials is True
        assert out.expires_at == out.sent_at + timedelta(days=14)

    def test_management_read_returns_status_only(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        out = tc.get_credentials(trainee_id=trainee.id, _={}, caller=mgr, db=db)
        assert type(out) is tc.CredentialsStatus
        assert "temp@example.com" not in out.model_dump_json()


class TestTheTraineeConfirms:
    def test_trainee_reads_the_values_while_they_exist(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        mine = tc.get_my_credentials(caller=trainee, db=db)
        assert (mine.flex_email, mine.clock_in_code) == ("temp@example.com", "1234")

    def test_confirm_destroys_the_values_and_audits(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        out = tc.confirm_my_credentials_changed(_={}, caller=trainee, db=db)

        assert out.flex_email is None and out.clock_in_code is None
        assert out.confirmed_at is not None and out.expires_at is None
        row = _row(db, trainee)
        assert row.flex_email is None and row.clock_in_code is None, "ciphertext must be gone, not just hidden"
        assert db.query(AuditLog).filter_by(action_type="credentials.confirmed").count() == 1

    def test_confirm_is_one_way(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        tc.confirm_my_credentials_changed(_={}, caller=trainee, db=db)
        with pytest.raises(HTTPException) as exc:
            tc.confirm_my_credentials_changed(_={}, caller=trainee, db=db)
        assert exc.value.status_code == 409

    def test_confirm_is_gated_to_trainees(self):
        """Dimension 2: the role gate, not only the in-body check."""
        import inspect
        dep = inspect.signature(tc.confirm_my_credentials_changed).parameters["_"].default.dependency
        assert dep is tc._trainee_only
        assert tc._trainee_only.allowed_roles == ["trainee"]

    def test_a_resend_is_a_new_handoff(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        tc.confirm_my_credentials_changed(_={}, caller=trainee, db=db)
        out = _send(db, mgr, trainee)
        assert out.has_credentials is True and out.confirmed_at is None
        assert tc.get_my_credentials(caller=trainee, db=db).flex_email == "temp@example.com"


class TestUnconfirmedCredentialsExpire:
    def _run(self, db, days=14):
        with patch.object(cleanup, "SessionLocal", return_value=db), \
             patch.object(db, "close"), \
             patch.object(cleanup.settings, "trainee_credential_retention_days", days):
            return cleanup.expire_trainee_credentials()

    def _age(self, db, trainee, days):
        row = _row(db, trainee)
        row.sent_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()

    def test_a_stale_unconfirmed_row_is_destroyed(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        self._age(db, trainee, 15)

        assert self._run(db)["expired"] == 1
        row = _row(db, trainee)
        assert row.flex_email is None and row.clock_in_code is None
        assert row.expired_at is not None and row.confirmed_at is None

        mine = tc.get_my_credentials(caller=trainee, db=db)
        assert mine.flex_email is None and mine.expired_at is not None

    def test_a_fresh_row_is_kept(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        self._age(db, trainee, 13)
        assert self._run(db)["expired"] == 0
        assert _row(db, trainee).flex_email is not None

    def test_a_confirmed_row_is_not_restamped_as_expired(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        tc.confirm_my_credentials_changed(_={}, caller=trainee, db=db)
        self._age(db, trainee, 30)
        assert self._run(db)["expired"] == 0
        assert _row(db, trainee).expired_at is None

    def test_zero_disables(self, db, people):
        mgr, trainee = people
        _send(db, mgr, trainee)
        self._age(db, trainee, 30)
        assert self._run(db, days=0) == {"skipped": True}
        assert _row(db, trainee).flex_email is not None
