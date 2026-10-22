"""Accounts are created with an UNverified email; signing in with the emailed
temporary password verifies it (ADR-564 D1/D3). The Lambda half is
tests/infra/test_adr564_email_verified_by_temp_password.py.

These walk every router, not a list of known paths: a create path added later
is held to the same rule without anyone remembering to add it here.
"""
import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
ROUTERS = sorted((APP / "routers").glob("*.py"))

# The only places allowed to write email_verified=true: each runs AFTER the new
# address proved itself, never at creation.
VERIFIED_TRUE_ALLOWED = {
    "companies.py": "ADR-451 owner email change -- after the link sent to the new inbox is used",
}


def _calls(src: str, name: str):
    for m in re.finditer(rf"\b{name}\(", src):
        yield src[m.start(): m.start() + 900]


def test_every_create_makes_the_email_unverified():
    seen = 0
    for path in ROUTERS:
        src = path.read_text()
        for block in _calls(src, "admin_create_user"):
            seen += 1
            assert '"email_verified", "Value": "true"' not in block, f"{path.name}: verified at creation"
    assert seen >= 4, f"expected the create paths, found {seen}"


def test_only_confirmed_flows_write_verified_true():
    offenders = [p.name for p in ROUTERS
                 if '"email_verified", "Value": "true"' in p.read_text() and p.name not in VERIFIED_TRUE_ALLOWED]
    assert not offenders, f"writes email_verified=true without a proof step: {offenders}"
    svc = (APP / "services" / "email_change.py").read_text()
    assert '"email_verified", "Value": "true"' in svc, "ADR-563's confirmed change is the other legitimate writer"


def test_every_handover_records_how_the_password_travelled():
    """A function that can return a temporary password (the email failed) must
    tell the sign-in Lambda, or that sign-in would 'verify' an unproven inbox."""
    missing = []
    for path in ROUTERS:
        tree = ast.parse(path.read_text())
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            body = ast.get_source_segment(path.read_text(), fn) or ""
            hands_over = ("temp_password=None if" in body) or ('"temp_password": temp_password' in body)
            if hands_over and "record_password_delivery" not in body:
                missing.append(f"{path.name}::{fn.name}")
    assert not missing, f"hands a password over without recording it: {missing}"


def test_registration_refuses_an_invite_with_no_email():
    src = (APP / "routers" / "registration.py").read_text()
    assert '"Value": employee.email or ""' not in src   # the Cognito attribute, not the display field
    assert "This invite has no email address" in src
