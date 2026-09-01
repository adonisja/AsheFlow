"""Which integration failures reach a super admin (ADR-336).

ADR-335 built PlatformAlert with one producer. This swept every external
integration against the test that matters — "can ONLY a super admin fix this?"
— and two of six changed hands on inspection:

  Discord, SES, Cognito  -> platform credentials, super admin
  ADP, Secrets Manager   -> per-company credentials, the tenant's own admin
  role_directory_check   -> neither; ADR-317 says it reports, never enforces

Found two silent failures worth fixing on their own merits: registration told a
new employee to check an email that had failed to send, and a failed Cognito
revoke left an offboarded employee able to sign in while the UI said otherwise.
"""
import ast
import inspect

import pytest

from app.routers import employees as EMP
from app.routers import registration as REG
from app.services import integration_alerts as IA


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1: registration stops promising an email it did not send ────────────────

def test_registration_does_not_promise_an_unsent_email():
    """THE worst finding. It returned "Check your email for sign-in credentials"
    unconditionally, so a new employee whose email bounced waited for something
    that would never arrive, with no reason to suspect the system."""
    src = _code_only(REG.complete_registration)
    assert "could not be sent" in src, "the failure case has no honest message"

    # Asserted on the CONDITIONAL, not the presence of the string. A mutation
    # replacing the test with `if True` — restoring the exact original bug —
    # kept both substrings and passed. Presence is not reachability (ADR-333),
    # and this is the third time that shape has surfaced.
    tree = ast.parse(src)
    cond = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.IfExp) and "could not be sent" in ast.unparse(n)),
        None,
    )
    assert cond is not None, "the message is not conditional at all"
    test_src = ast.unparse(cond.test)
    assert "email_sent" in test_src, (
        f"the honest message is not gated on delivery (test is {test_src!r})"
    )


def test_the_registration_response_reports_delivery():
    src = _code_only(REG.complete_registration)
    assert "'email_sent': email_sent" in src or '"email_sent": email_sent' in src


def test_ses_failures_raise_a_platform_alert():
    """SES is platform infrastructure — a company admin cannot verify a sending
    identity or lift a sandbox limit."""
    for fn in (REG.complete_registration, EMP.create_employee):
        src = _code_only(fn)
        assert "EMAIL_DELIVERY_FAILED" in src, f"{fn.__name__} does not alert on SES failure"


def test_the_email_alert_carries_no_recipient_address():
    """Dim 7 — the address is the payload of the thing that failed, not
    something a CROSS-TENANT board needs. Putting it there exposes an employee's
    email on a surface spanning every tenant."""
    assert "@" not in IA.EMAIL_DOWN_MESSAGE

    # Asserted on the CALL NODE. A character window caught `employee.email` from
    # the log line above it — where the address legitimately belongs, since a
    # log is not a cross-tenant board. Eighth character-window false positive
    # this week; the AST version was no harder to write.
    tree = ast.parse(_code_only(REG.complete_registration))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "raise_platform_alert"
    ]
    assert calls, "no platform alert is raised on SES failure"
    for c in calls:
        rendered = ast.unparse(c)
        assert "employee.email" not in rendered, (
            f"the alert call passes the recipient address: {rendered}"
        )


# ── D2: a failed revocation is reported, not swallowed ───────────────────────

def test_the_revoke_helper_reports_its_outcome():
    """It returned None and swallowed, while its call site claimed "blocks token
    refresh immediately" — false when Cognito is unreachable."""
    src = _code_only(EMP._cognito_revoke_access)
    assert "return False" in src and "return True" in src
    assert inspect.signature(EMP._cognito_revoke_access).return_annotation is bool


def test_a_failed_revocation_raises_a_critical_alert():
    """The only SECURITY exposure in the sweep, as opposed to a visibility gap:
    an offboarded employee keeps working credentials."""
    src = _code_only(EMP.deactivate_employee)
    assert "IDENTITY_REVOCATION_FAILED" in src
    assert "'critical'" in src or '"critical"' in src


def test_the_deactivate_request_still_succeeds():
    """The DB write is already committed; failing the request would leave the
    caller unable to tell what happened."""
    tree = ast.parse(_code_only(EMP.deactivate_employee))
    guard = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.If) and "_cognito_revoke_access" in ast.unparse(n.test)),
        None,
    )
    assert guard is not None, "the revoke result is not checked"
    assert not [n for n in ast.walk(guard) if isinstance(n, ast.Raise)], (
        "a failed revocation must not fail the request"
    )


def test_the_revocation_message_says_what_is_now_untrue():
    """"Cognito call failed" is not actionable. "Someone may still be able to
    sign in" is."""
    assert "still be able to sign in" in IA.IDENTITY_REVOCATION_MESSAGE


# ── D3: per-company integrations stay with company admins ────────────────────

def test_adp_is_per_company_and_therefore_not_a_platform_alert():
    """ADPIntegration.company_id is nullable=False and unique per company, with
    per-company Secrets Manager ARNs. One tenant's expired client secret is
    their own admin's to rotate — and routing it to a cross-tenant board would
    expose one tenant's misconfiguration to a surface spanning all of them."""
    from app.models.adp_integration import ADPIntegration
    assert ADPIntegration.__table__.columns["company_id"].nullable is False

    from app.routers import adp as ADP
    src = inspect.getsource(ADP)
    assert "raise_platform_alert" not in src, (
        "ADP failures must not reach the platform board (ADR-336 D3)"
    )


# ── D4: the directory check keeps degrading silently, by design ──────────────

def test_the_role_directory_check_does_not_alert():
    """ADR-317 — it reports, never enforces. A diagnostic that alerts when it
    cannot run would invert its own design, and a Cognito outage must not block
    a login."""
    from app.services import role_directory_check as RDC
    src = inspect.getsource(RDC)
    assert "raise_platform_alert" not in src


# ── D5: one alert type per integration ───────────────────────────────────────

def test_one_type_per_integration_not_per_call_site():
    """The dedup key is (alert_type, company_id), so a bulk invite failing for
    40 rows collapses to ONE incident with occurrence_count=40 rather than 40
    board entries."""
    src = inspect.getsource(EMP)
    # both email call sites share the one type
    assert src.count("EMAIL_DELIVERY_FAILED") >= 2
    assert "EMAIL_INVITE_FAILED" not in src and "EMAIL_BULK_FAILED" not in src
