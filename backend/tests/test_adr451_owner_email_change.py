"""ADR-451 D4/D4a/D5: an Owner email change is verified before it lands.

WHY THIS PATH EXISTS AT ALL. An Owner who can sign in changes their own address
through /employees/me/email/request-change, which already verifies through
Cognito (ADR-452 D5). This is for the Owner who CANNOT sign in -- which is the
only reason a super admin would be doing it, and the case Cognito cannot cover.

Building D5 first showed that NOTHING wrote `pending_email`, so an expiry sweep
would have scanned for rows that could not exist. D4a records that finding.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPANIES = ROOT / "backend" / "app" / "routers" / "companies.py"
CLEANUP = ROOT / "backend" / "app" / "tasks" / "cleanup.py"
BEAT = ROOT / "backend" / "app" / "celery_app.py"
EMAIL = ROOT / "backend" / "app" / "services" / "email.py"


def _fn(path: pathlib.Path, name: str):
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _src(path: pathlib.Path, name: str, span: int = 3500) -> str:
    s = path.read_text()
    i = s.index(f"def {name}")
    return s[i:i + span]


class TestTheLiveEmailIsNeverWrittenFirst:
    """THE CORE OF D4. Writing first and verifying later means a typo locks the
    Owner out of a live tenant, and the only person who could correct it is the
    one who cannot sign in."""

    def test_the_request_writes_only_pending_email(self):
        body = _src(COMPANIES, "request_owner_email_change")
        assert "owner.pending_email = new_email" in body
        assert "owner.email = " not in body, (
            "the request path writes the live email — a typo would lock the "
            "Owner out (ADR-451 D4)"
        )

    def test_the_live_email_changes_only_on_confirmation(self):
        body = _src(COMPANIES, "confirm_owner_email_change")
        assert "owner.email = owner.pending_email" in body

    def test_cancelling_clears_pending_and_leaves_email_alone(self):
        """AST, not substring: `owner.email` matches inside
        `owner.pending_email`, so a text check reports a bug that is not there.
        """
        fn = _fn(COMPANIES, "cancel_owner_email_change")
        written = {
            n.attr for node in ast.walk(fn)
            if isinstance(node, ast.Assign)
            for n in node.targets if isinstance(n, ast.Attribute)
        }
        assert "pending_email" in written
        assert "email" not in written, \
            "cancelling writes the live email — there is nothing to write"


class TestTheTokenProvesControlOfTheNewAddress:
    def test_the_verification_goes_to_the_new_address(self):
        """Sending it anywhere else proves nothing about the new mailbox."""
        body = _src(COMPANIES, "request_owner_email_change")
        assert "to_email=new_email" in body

    def test_confirm_is_unauthenticated(self):
        """The person confirming may be unable to sign in — that is the whole
        reason this path exists. The token IS the authentication."""
        src = COMPANIES.read_text()
        assert '@public_router.post("/owner/email-change/confirm"' in src
        args = ast.dump(_fn(COMPANIES, "confirm_owner_email_change").args)
        assert "get_super_admin" not in args
        assert "get_caller_employee" not in args

    def test_a_used_or_expired_token_is_refused(self):
        body = _src(COMPANIES, "confirm_owner_email_change")
        assert "record.used" in body
        assert "pending_email_expires_at" in body

    def test_the_token_is_burned_on_use(self):
        body = _src(COMPANIES, "confirm_owner_email_change")
        assert "record.used = True" in body

    def test_failures_do_not_distinguish_missing_from_expired(self):
        """Otherwise the endpoint is a probe for live tokens."""
        body = _src(COMPANIES, "confirm_owner_email_change")
        assert body.count("no longer valid") == 1, (
            "more than one failure message — the differences leak which "
            "tokens exist"
        )


class TestTheRequestGuards:
    def test_it_is_super_admin_only(self):
        args = ast.dump(_fn(COMPANIES, "request_owner_email_change").args)
        assert "get_super_admin" in args

    def test_an_address_in_use_is_refused(self):
        body = _src(COMPANIES, "request_owner_email_change")
        assert "already in use" in body

    def test_the_same_address_is_refused(self):
        body = _src(COMPANIES, "request_owner_email_change")
        assert "already the Owner's email" in body

    def test_the_body_forbids_unknown_keys(self):
        src = COMPANIES.read_text()
        i = src.index("class OwnerEmailChangeRequest")
        assert 'extra="forbid"' in src[i:i + 300]


class TestTheExpirySweep:
    """D5. The revert is that `email` was never written."""

    def test_it_clears_pending_and_never_touches_email(self):
        body = _src(CLEANUP, "expire_owner_email_changes")
        assert "emp.pending_email = None" in body
        assert "emp.email" not in body, (
            "the sweep touches the live email — there is nothing to restore, "
            "because it was never written (ADR-451 D5)"
        )

    def test_it_only_matches_expired_rows(self):
        body = _src(CLEANUP, "expire_owner_email_changes")
        assert "pending_email.isnot(None)" in body
        assert "pending_email_expires_at < now" in body

    def test_it_logs_no_address(self):
        """Dimension 7: a log is a wider audience than the record.

        Reads the logger CALL from the AST -- a character window around
        `logger.info` swept up the docstring, which legitimately says
        "pending_email" while the log itself does not.
        """
        fn = _fn(CLEANUP, "expire_owner_email_changes")
        calls = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in {"info", "warning", "error"}
        ]
        assert calls, "the sweep logs nothing at all"
        args = " ".join(ast.dump(a) for c in calls for a in c.args)
        assert "pending_email" not in args, \
            "the sweep logs the pending address (Dimension 7)"
        assert "id" in args, "the log does not identify the row at all"

    def test_it_is_scheduled(self):
        src = BEAT.read_text()
        assert "app.tasks.cleanup.expire_owner_email_changes" in src, \
            "the sweep exists but never runs"

    def test_the_window_is_three_days(self):
        src = COMPANIES.read_text()
        assert "OWNER_EMAIL_CHANGE_DAYS = 3" in src
        assert "invite_expiry_days" not in _src(COMPANIES, "request_owner_email_change"), (
            "the window reuses the per-tenant invite expiry — this is a "
            "correction to a LIVE account and must not sit open at a tenant's "
            "discretion (ADR-451 D5)"
        )


class TestTheEmailSaysNothingHasChangedYet:
    def test_it_tells_an_unexpecting_reader_to_ignore_it(self):
        """A mail about an account you did not ask to change is alarming unless
        it says plainly that nothing happens without the link."""
        body = _src(EMAIL, "send_owner_email_change_email", 6000)
        assert "Ignore this email" in body or "ignore this email" in body
        assert "nothing changes" in body
