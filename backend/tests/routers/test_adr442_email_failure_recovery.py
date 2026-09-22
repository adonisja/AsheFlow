"""A failed email must leave a way back (ADR-442).

SES sandbox mode refuses unverified RECIPIENTS, so a send can fail for reasons
the application cannot control. What it can control is whether the failure
leaves work recoverable.
"""
import inspect


class TestTheCredentialsResetStaysRecoverable:
    """The temp password is generated, set in Cognito, and never persisted —
    the email was its ONLY delivery channel. Raising without it leaves an
    account whose password exists and which nobody knows."""

    def test_a_failed_send_returns_the_password(self):
        from app.routers.registration import resend_credentials

        src = inspect.getsource(resend_credentials)
        # The EMAIL failure handler specifically. An earlier `except
        # ClientError` in this function handles a Cognito failure, where
        # raising IS correct — the password was never set, so there is nothing
        # to hand back.
        fail = src[src.index("Credentials resend email failed"):]
        assert "temp_password" in fail, (
            "a failed send must return the password, or the account is "
            "stranded: retrying just generates another undeliverable one"
        )
        assert "raise HTTPException" not in fail, (
            "raising discards the only copy of the credential"
        )

    def test_a_successful_send_returns_no_credential(self):
        """Returned ONLY on failure. When email works it is the better channel,
        and there is no reason to put a live password in a second place."""
        from app.routers.registration import resend_credentials

        src = inspect.getsource(resend_credentials)
        tail = src[src.rindex("return {"):]
        assert "temp_password" not in tail, (
            "the success path must not return the credential"
        )
        assert "email_delivered" in tail

    def test_both_paths_say_whether_email_was_delivered(self):
        """The caller cannot tell a delivered reset from an undelivered one by
        status code alone — both are 200 now."""
        from app.routers.registration import resend_credentials

        src = inspect.getsource(resend_credentials)
        assert src.count("email_delivered") == 2


class TestTheSandboxIsNamed:
    """"email delivery failed" sent an operator to the IAM policies first,
    which were identical across environments and fine. The cause was in the
    error: an AccessDenied whose RESOURCE is the recipient's identity ARN."""

    def test_every_sender_uses_the_shared_handler(self):
        """Three senders, one diagnosis. A sender with its own log line would
        silently lose the hint."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2]
               / "app" / "services" / "email.py").read_text()
        # Counts CALLS, not the definition: `def _log_ses_failure(` also
        # contains the string, which made this read one too many and pass for
        # the wrong reason on a file where a sender had been missed.
        calls = src.count("        _log_ses_failure(")
        handlers = src.count("except ClientError")
        assert calls == handlers, (
            f"{handlers} SES error handlers but {calls} route through "
            f"_log_ses_failure — one would lose the sandbox hint"
        )

    def test_the_hint_is_specific_to_the_sandbox_signature(self):
        """It must not fire on unrelated failures — a wrong diagnosis in a log
        is worse than none."""
        from botocore.exceptions import ClientError

        from app.services.email import _log_ses_failure

        src = inspect.getsource(_log_ses_failure)
        assert 'code == "AccessDenied"' in src
        assert 'f"identity/{to_email}"' in src, (
            "the hint must key on the RECIPIENT appearing as the resource, "
            "which is what distinguishes a sandbox refusal from a real IAM gap"
        )
        # And it must not blow up on an error with no response body.
        _log_ses_failure("x@example.com", ClientError({}, "SendEmail"))


class TestTheBootstrapResendNeedsNoNewEndpoint:
    def test_bootstrap_is_idempotent(self):
        """ADR-442 D1. The resend is the same endpoint: given an email that
        already has an admin row, it reuses it and issues a fresh token. A
        dedicated /bootstrap/resend would duplicate that and drift."""
        from app.routers.companies import bootstrap_company_admin

        src = inspect.getsource(bootstrap_company_admin)

        # Asserted as BEHAVIOUR, not as the presence of the word "idempotent" in
        # a comment. ADR-451 rewrote that comment (the match moved from email to
        # is_bootstrap_admin) and this test failed while the property it cares
        # about was untouched -- a comment is not the contract.
        assert "InviteToken.employee_id == employee.id).delete()" in src, (
            "a resend must invalidate the prior token"
        )
        # Re-running for a PENDING admin must reuse the row rather than insert a
        # second one. ADR-451 D1 strengthened this: the lookup is now on the
        # bootstrap flag, so even a CHANGED email reuses the row instead of
        # silently creating a duplicate admin.
        assert "employee.email = payload.email" in src, (
            "a re-run no longer updates the pending admin in place"
        )
        assert "is_bootstrap_admin" in src, (
            "the existing-admin lookup is not on the bootstrap flag (ADR-451 D1)"
        )
