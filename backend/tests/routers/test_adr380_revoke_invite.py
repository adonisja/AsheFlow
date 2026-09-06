"""A wrong invite can be revoked without destroying the employee (ADR-380 D3).

Before this, a manager who invited the wrong person -- or the right person at
the wrong address -- had exactly one option: delete the whole employee row,
taking its audit history with it.

Re-inviting DOES replace the token (send_invite deletes prior ones first), but
that requires knowing the address is wrong AND having a correct one to hand. A
manager who only knows "that was a mistake" had nothing.

There is no orphaned-token security hole either way -- invite_tokens.employee_id
is ondelete=CASCADE -- so this gap was operational, not a leak. That is why it
ships after the bugs that destroyed data.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.routers.registration import revoke_invite
from tests.conftest import SEED_COMPANY_ID, make_employee

NOW = datetime.now(timezone.utc)


def _pending(db, name="Pending Hire", username=None):
    e = make_employee(db, "trainee", name)
    e.username = username
    e.account_status = "pending_verification"
    e.is_active = False
    db.commit()
    return e


def _token(db, employee, company_id=None, used=False):
    t = InviteToken(
        id=uuid.uuid4(),
        token=uuid.uuid4().hex,
        company_id=company_id or SEED_COMPANY_ID,
        employee_id=employee.id,
        expires_at=NOW + timedelta(days=7),
        used=used,
    )
    db.add(t)
    db.commit()
    return t


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Disable the shared rate limiter for these unit tests.

    The endpoint is limited to 10/minute and slowapi's counter is process-wide,
    so tests after the tenth in a run get a 429 that has nothing to do with what
    they are asserting. The limit itself is verified by reading the decorator,
    not by exhausting it.
    """
    from app.api.ratelimit import limiter

    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


def _request():
    """A real starlette Request.

    The endpoint carries @limiter.limit, and slowapi inspects the `request`
    argument and rejects anything that is not a Request instance -- so None does
    not work here even though the endpoint body never touches it.
    """
    return Request({
        "type": "http", "method": "DELETE", "path": "/registration/invite",
        "headers": [], "client": ("127.0.0.1", 1), "query_string": b"",
    })


def _call(db, employee_id, caller):
    return revoke_invite(
        request=_request(), employee_id=employee_id, caller=caller, _=None, db=db,
    )


class TestRevoking:
    def test_it_deletes_the_live_token(self, db):
        emp = _pending(db)
        _token(db, emp)
        caller = make_employee(db, "management", "The Manager")

        out = _call(db, emp.id, caller)

        assert out["revoked"] is True
        assert db.query(InviteToken).filter(
            InviteToken.employee_id == emp.id).first() is None

    def test_it_does_not_destroy_the_employee(self, db):
        """The whole point. Deleting the row was the only prior option, and it
        takes the audit history with it."""
        emp = _pending(db)
        _token(db, emp)
        caller = make_employee(db, "management", "The Manager")

        _call(db, emp.id, caller)

        survivor = db.query(Employee).filter(Employee.id == emp.id).first()
        assert survivor is not None
        assert survivor.account_status == "pending_verification", (
            "the row must stay invitable so the manager can correct the email "
            "and re-invite"
        )

    def test_it_writes_an_audit_row(self, db):
        from app.models.audit_log import AuditLog

        emp = _pending(db)
        _token(db, emp)
        caller = make_employee(db, "management", "The Manager")
        before = db.query(AuditLog).filter(
            AuditLog.action_type == "employee.invite_revoked").count()

        _call(db, emp.id, caller)

        assert db.query(AuditLog).filter(
            AuditLog.action_type == "employee.invite_revoked").count() == before + 1

    def test_the_audit_row_does_not_record_the_token(self, db):
        """Matching send_invite: an audit row is readable by other admins, and a
        live token is a working credential."""
        from app.models.audit_log import AuditLog

        emp = _pending(db)
        tok = _token(db, emp)
        caller = make_employee(db, "management", "The Manager")

        _call(db, emp.id, caller)

        row = db.query(AuditLog).filter(
            AuditLog.action_type == "employee.invite_revoked").order_by(
            AuditLog.created_at.desc()).first()
        assert tok.token not in str(row.after_snapshot)


class TestTheGuards:
    def test_an_unknown_employee_is_404(self, db):
        caller = make_employee(db, "admin", "An Admin")
        with pytest.raises(HTTPException) as exc:
            _call(db, uuid.uuid4(), caller)
        assert exc.value.status_code == 404

    def test_another_tenants_employee_is_404(self, db):
        """Dimension 1. A real row, in another company -- a random UUID would
        404 whether or not the query is scoped and so proves nothing."""
        other = Employee(
            id=uuid.uuid4(), company_id=uuid.uuid4(), name="Other Tenant",
            role="trainee", is_active=False, account_status="pending_verification",
            reset_on_graduation=False, hr_system_id_adp=uuid.uuid4(),
            hr_system_id_adp_verified=False,
        )
        db.add(other)
        db.commit()
        caller = make_employee(db, "admin", "An Admin")

        with pytest.raises(HTTPException) as exc:
            _call(db, other.id, caller)
        assert exc.value.status_code == 404

    def test_a_registered_employee_is_refused(self, db):
        """Their token is already spent, so deleting it would report success
        while revoking nothing -- and the caller wanted to stop someone signing
        in, which is deactivation."""
        emp = _pending(db, name="Already Registered", username="already.registered")
        _token(db, emp, used=True)
        caller = make_employee(db, "admin", "An Admin")

        with pytest.raises(HTTPException) as exc:
            _call(db, emp.id, caller)
        assert exc.value.status_code == 409
        assert "deactivate" in exc.value.detail.lower(), (
            "the refusal must name what the caller should do instead"
        )

    def test_no_pending_invite_reports_rather_than_failing(self, db):
        """The desired end state already holds. Reported so the caller knows
        nothing was there rather than believing they revoked something."""
        emp = _pending(db, name="No Invite")
        caller = make_employee(db, "admin", "An Admin")

        out = _call(db, emp.id, caller)

        assert out["revoked"] is False

    def test_the_gate_matches_send_invite(self, db):
        """An invite is the credential that lets someone into the tenant;
        revoking one must not be reachable by anyone who cannot issue one."""
        import inspect

        from app.routers.registration import revoke_invite, send_invite

        assert 'RoleChecker(["management", "admin"])' in inspect.getsource(revoke_invite)
        assert 'RoleChecker(["management", "admin"])' in inspect.getsource(send_invite)


class TestReInviteStillWorks:
    def test_the_employee_can_be_invited_again_after_revoking(self, db):
        """Revoke must leave the row in a state send_invite accepts, or the
        correction workflow this exists for does not complete."""
        emp = _pending(db)
        _token(db, emp)
        caller = make_employee(db, "management", "The Manager")

        _call(db, emp.id, caller)

        # send_invite refuses on account_status == "active" and on no email.
        assert emp.account_status != "active"
        assert db.query(InviteToken).filter(
            InviteToken.employee_id == emp.id).first() is None, (
            "a stale token would be replaced by send_invite anyway, but leaving "
            "one means the revoke did not happen"
        )


class TestItIsRateLimited:
    """The tests above disable the limiter so a 429 does not masquerade as a
    logic failure. That removes coverage of the limit, so assert it separately.

    An invite is the credential that admits someone to the tenant; revoking is
    equally an access-control write and gets the same ceiling as issuing one.
    """

    def test_revoke_carries_a_rate_limit(self):
        import inspect

        from app.routers import registration as R

        src = inspect.getsource(R)
        i = src.index("def revoke_invite")
        # The decorators sit immediately above the def.
        window = src[max(0, i - 300):i]
        assert "@limiter.limit(" in window, "revoke_invite lost its rate limit"

    def test_it_matches_the_send_invite_ceiling(self):
        import inspect

        from app.routers import registration as R

        src = inspect.getsource(R)
        for name in ("def send_invite", "def revoke_invite"):
            i = src.index(name)
            assert '@limiter.limit("10/minute")' in src[max(0, i - 300):i], (
                f"{name} does not carry the 10/minute ceiling"
            )
