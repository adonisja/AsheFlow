"""An employee is found by the Cognito identity, never by email (ADR-560).

Proved on staging 2026-10-21: a throwaway Cognito user `Discord_probe559…`,
NO MFA and no groups, sharing only manager.test's email:

  GET /employees/me            -> 200 {'username': 'manager.test', 'role': 'management'}
  GET /employees/me/mfa-status -> 200 {'enrolled': True, 'blocked': False}

The resolver's email fallback turned "same email" into "same person". These
tests replay that against the real resolver, then pin the federated sign-in
pieces that fed it as gone.
"""
import ast
import importlib.util
import pathlib
import uuid

from app.api import deps
from tests.conftest import make_employee

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _token(sub, username, email):
    return {"id": sub, "username": username, "email": email, "cognito_groups": []}


# ── the resolver ──────────────────────────────────────────────────────────

def test_a_different_account_with_the_same_email_is_not_the_employee(db):
    """The staging probe, replayed: matching email, different sub and username."""
    mgr = make_employee(db, role="management", name="Manager Test")
    mgr.username, mgr.email, mgr.cognito_sub = "manager.test", "manager@test.com", str(uuid.uuid4())
    db.commit()
    found, _ = deps._resolve_employee_from_cognito(
        _token(str(uuid.uuid4()), "Discord_probe559abc", "manager@test.com"), db)
    assert found is None


def test_a_platform_account_sharing_an_employees_email_is_not_them(db):
    """Prod's exposure: super admin / support / surveyor have no Employee row."""
    emp = make_employee(db, role="walker", name="W")
    emp.username, emp.email = "w.one", "shared@example.com"
    db.commit()
    found, _ = deps._resolve_employee_from_cognito(
        _token(str(uuid.uuid4()), "test.surveyor", "shared@example.com"), db)
    assert found is None


def test_the_cognito_sub_still_finds_the_employee(db):
    emp = make_employee(db, role="walker", name="W")
    emp.cognito_sub = str(uuid.uuid4()); db.commit()
    found, _ = deps._resolve_employee_from_cognito(_token(emp.cognito_sub, "anything", None), db)
    assert found is not None and found.id == emp.id


def test_the_username_still_finds_an_unstamped_employee(db):
    """Kept: Cognito usernames are unique in the pool and set by us."""
    emp = make_employee(db, role="walker", name="W")
    emp.username = "danny.rivera"; db.commit()
    found, _ = deps._resolve_employee_from_cognito(_token(str(uuid.uuid4()), "danny.rivera", None), db)
    assert found is not None and found.id == emp.id


def test_the_resolver_never_queries_email_or_discord_id():
    """A structural guard: re-adding either fallback fails here, not in prod."""
    src = (ROOT / "backend/app/api/deps.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_resolve_employee_from_cognito")
    attrs = {f"{a.value.id}.{a.attr}" for a in ast.walk(fn)
             if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name)}
    assert "Employee.email" not in attrs and "Employee.discord_id" not in attrs


# ── federated sign-in is gone from both clients and the client script ──────

def test_web_has_no_federated_sign_in():
    for rel in ("frontend/src/components/auth/Login.tsx", "frontend/src/contexts/AuthContext.tsx",
                "frontend/src/main.tsx"):
        src = (ROOT / rel).read_text()
        assert "signInWithRedirect" not in src and "oauth:" not in src and "federatedError" not in src, rel


def test_mobile_has_no_federated_sign_in():
    for rel in ("mobile/src/screens/Auth/LoginScreen.tsx", "mobile/src/contexts/AuthContext.tsx"):
        src = (ROOT / rel).read_text()
        assert "signInWithProvider" not in src and "oauth2/authorize" not in src \
            and "oauth2/token" not in src, rel
    assert not (ROOT / "mobile/src/components/ui/BrandIcons.tsx").exists()


def _script():
    spec = importlib.util.spec_from_file_location("ccu", ROOT / "scripts/cognito_client_update.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_the_client_script_strips_providers_and_never_adds_one():
    s = _script()
    fields = s.accepted_fields()
    base = {"UserPoolId": "p", "ClientId": "c"}
    with_idps = s.request({**base, "SupportedIdentityProviders": ["COGNITO", "Discord", "Google"]}, ["locale"], fields)
    assert with_idps["SupportedIdentityProviders"] == ["COGNITO"]
    none_live = s.request({**base, "SupportedIdentityProviders": None}, ["locale"], fields)
    assert "SupportedIdentityProviders" not in none_live, "prod's null list must stay null"
    assert s.WRITE_ATTRIBUTES["us-east-2_SvVO2ofAb"] == ["locale"], "staging no longer needs email"
