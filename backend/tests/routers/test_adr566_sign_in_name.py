"""A person chooses their own sign-in name; an admin can only clear one (ADR-566 D4).

The sign-in name is Cognito's `preferred_username`, accepted at sign-in as an
alias by the pools ADR-566 creates. Measured on the new staging pool
(2026-10-22): Cognito itself refuses an alias equal to any other account's
username or alias, case-insensitively (AliasExistsException), and accepts
"@" -- so the shape rule is ours and uniqueness is Cognito's.

Every Cognito call is stubbed: locally the settings carry a real pool id.
"""
import ast
import inspect
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.routers import employees as E
from app.routers import platform_account as P
from app.routers import platform_alerts as PA
from app.services import account_security, sign_in_name
from tests.conftest import SEED_COMPANY_ID


@pytest.fixture(autouse=True)
def _fresh_cache():
    sign_in_name._alias_pools.clear()
    yield
    sign_in_name._alias_pools.clear()


class _Redis:
    def __init__(self): self.d = {}
    def incr(self, k): self.d[k] = int(self.d.get(k, 0)) + 1; return self.d[k]
    def expire(self, k, ttl): pass


def _cog(alias=True, current=None, groups=(), sub=None, username="the.person"):
    c = MagicMock()
    c.describe_user_pool.return_value = {"UserPool": {"AliasAttributes": ["preferred_username"] if alias else None}}
    attrs = [{"Name": "sub", "Value": sub or str(uuid.uuid4())}]
    if current:
        attrs.append({"Name": "preferred_username", "Value": current})
    c.admin_get_user.return_value = {"Username": username, "UserAttributes": attrs}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    c.sub = attrs[0]["Value"]
    return c


@contextmanager
def _aws(cog, redis=None):
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch.object(account_security, "_redis", return_value=redis or _Redis()):
        yield


def _emp(db, role="walker", username="the.person", company=SEED_COMPANY_ID):
    e = Employee(id=uuid.uuid4(), company_id=company, name=f"E {username}", role=role, is_active=True,
                 username=username, cognito_sub=str(uuid.uuid4()), email=f"{username}@example.com",
                 account_status="active")
    db.add(e); db.commit()
    return e


def _audits(db, action):
    return db.query(AuditLog).filter(AuditLog.action_type == action).all()


# ── the shape rule ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [("Adon_J", "adon_j"), ("  sam.k-2 ", "sam.k-2"), ("abc", "abc"),
                                        ("a" * 30, "a" * 30)])
def test_a_good_name_is_accepted_and_lowercased(raw, expect):
    assert sign_in_name.normalise(raw) == expect


@pytest.mark.parametrize("raw", ["ab", "a" * 31, "1abc", "_abc", "a@b.co", "two words", "", "émile", "a+b"])
def test_a_bad_name_is_refused_with_the_rule(raw):
    with pytest.raises(sign_in_name.SignInNameError) as exc:
        sign_in_name.normalise(raw)
    assert exc.value.status == 422 and "starting with a letter" in exc.value.detail


# ── availability follows the pool ─────────────────────────────────────────

def test_available_only_on_a_pool_with_the_alias():
    with _aws(_cog(alias=False)):
        assert sign_in_name.available() is False
    sign_in_name._alias_pools.clear()
    with _aws(_cog(alias=True)):
        assert sign_in_name.available() is True


def test_a_failed_pool_read_is_not_cached():
    """A transient failure must not switch the feature off until a restart."""
    bad = _cog(); bad.describe_user_pool.side_effect = ClientError({"Error": {"Code": "Throttling"}}, "Describe")
    with _aws(bad):
        assert sign_in_name.available() is False
    with _aws(_cog(alias=True)):
        assert sign_in_name.available() is True


def test_nothing_is_written_on_a_pool_without_the_alias(db):
    cog = _cog(alias=False)
    with _aws(cog), pytest.raises(sign_in_name.SignInNameError) as exc:
        sign_in_name.apply_sign_in_name(db, username="the.person", raw="sammy", rate_key="k",
                              audit={"company_id": None, "actor_id": None, "target_table": "t", "target_id": "x"})
    assert exc.value.status == 409 and not cog.admin_update_user_attributes.called


# ── setting your own ──────────────────────────────────────────────────────

def test_the_person_sets_their_own_and_it_is_audited(db):
    emp, cog = _emp(db), _cog(current="old.name")
    with _aws(cog):
        out = E.set_sign_in_name(payload=E._SignInNameIn(sign_in_name="Sammy"), caller=emp, db=db)
    assert out == {"sign_in_name": "sammy"}
    kw = cog.admin_update_user_attributes.call_args.kwargs
    assert kw["Username"] == "the.person"
    assert kw["UserAttributes"] == [{"Name": "preferred_username", "Value": "sammy"}]
    (row,) = _audits(db, "account.sign_in_name_set")
    assert row.after_snapshot == {"from": "old.name", "to": "sammy"} and str(row.target_id) == str(emp.id)


def test_a_taken_name_is_a_friendly_409(db):
    emp, cog = _emp(db), _cog()
    cog.admin_update_user_attributes.side_effect = ClientError(
        {"Error": {"Code": "AliasExistsException", "Message": "User account already exists for the alias."}}, "U")
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.set_sign_in_name(payload=E._SignInNameIn(sign_in_name="taken"), caller=emp, db=db)
    assert exc.value.status_code == 409 and "taken" in exc.value.detail
    assert not _audits(db, "account.sign_in_name_set")


def test_your_own_username_is_not_a_sign_in_name(db):
    emp, cog = _emp(db), _cog()
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.set_sign_in_name(payload=E._SignInNameIn(sign_in_name="The.Person"), caller=emp, db=db)
    assert exc.value.status_code == 400 and not cog.admin_update_user_attributes.called


def test_changes_are_rate_limited(db):
    emp, cog, r = _emp(db), _cog(), _Redis()
    with _aws(cog, r):
        for i in range(account_security.MAX_CODE_REQUESTS_PER_HOUR):
            E.set_sign_in_name(payload=E._SignInNameIn(sign_in_name=f"name{i}"), caller=emp, db=db)
        with pytest.raises(HTTPException) as exc:
            E.set_sign_in_name(payload=E._SignInNameIn(sign_in_name="onemore"), caller=emp, db=db)
    assert exc.value.status_code == 429


def test_get_hides_the_name_until_the_pool_supports_it(db):
    emp = _emp(db)
    with _aws(_cog(alias=False, current="leftover")):
        out = E.get_sign_in_name(caller=emp)
    assert out["available"] is False and out["sign_in_name"] is None


def test_clearing_your_own(db):
    emp, cog = _emp(db), _cog(current="sammy")
    with _aws(cog):
        assert E.clear_own_sign_in_name(caller=emp, db=db) == {"cleared": True}
    assert cog.admin_delete_user_attributes.call_args.kwargs["UserAttributeNames"] == ["preferred_username"]
    (row,) = _audits(db, "account.sign_in_name_cleared")
    assert row.after_snapshot == {"was": "sammy", "cleared_by": "self"}


def test_clearing_when_there_is_none_changes_nothing(db):
    emp, cog = _emp(db), _cog(current=None)
    with _aws(cog):
        assert E.clear_own_sign_in_name(caller=emp, db=db) == {"cleared": False}
    assert not cog.admin_delete_user_attributes.called and not _audits(db, "account.sign_in_name_cleared")


@pytest.mark.parametrize("bad", [{"sign_in_name": "x" * 65}, {"sign_in_name": "ok", "extra": 1}, {}])
def test_the_request_body_is_bounded(bad):
    with pytest.raises(ValidationError):
        E._SignInNameIn(**bad)
    with pytest.raises(ValidationError):
        P._SignInNameIn(**bad)


# ── an admin clears, never chooses ────────────────────────────────────────

def test_an_admin_clears_an_employees_name(db):
    admin, target, cog = _emp(db, role="admin", username="the.admin"), _emp(db), _cog(current="rude")
    with _aws(cog):
        out = E.admin_clear_sign_in_name(employee_id=target.id, db=db, caller=admin,
                                         current_user={"cognito_groups": ["admin"]})
    assert out == {"cleared": True}
    (row,) = _audits(db, "account.sign_in_name_cleared")
    assert row.after_snapshot["cleared_by"] == "tenant_admin" and str(row.target_id) == str(target.id)


def test_another_companys_employee_is_not_found(db):
    admin, cog = _emp(db, role="admin", username="the.admin"), _cog(current="x")
    other = _emp(db, username="else.where", company=uuid.uuid4())
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.admin_clear_sign_in_name(employee_id=other.id, db=db, caller=admin,
                                   current_user={"cognito_groups": ["admin"]})
    assert exc.value.status_code == 404 and not cog.admin_delete_user_attributes.called


def test_management_cannot_clear_an_admins_name(db):
    mgr, target, cog = _emp(db, role="management", username="the.mgr"), _emp(db, role="admin", username="an.admin"), _cog(current="x")
    with _aws(cog), pytest.raises(HTTPException) as exc:
        E.admin_clear_sign_in_name(employee_id=target.id, db=db, caller=mgr,
                                   current_user={"cognito_groups": ["management"]})
    assert exc.value.status_code == 403 and not cog.admin_delete_user_attributes.called


def test_an_admin_uses_my_account_for_their_own(db):
    admin = _emp(db, role="admin", username="the.admin")
    with pytest.raises(HTTPException) as exc:
        E.admin_clear_sign_in_name(employee_id=admin.id, db=db, caller=admin,
                                   current_user={"cognito_groups": ["admin"]})
    assert exc.value.status_code == 400


def test_only_the_self_service_endpoints_can_set_a_name():
    """The owner's rule, pinned structurally: apply_sign_in_name is called from exactly
    the two "my own" endpoints, and nowhere an admin is the caller."""
    callers = set()
    for mod in (E, P, PA):
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.FunctionDef):
                for n in ast.walk(node):
                    if isinstance(n, ast.Attribute) and n.attr == "apply_sign_in_name":
                        callers.add((mod.__name__.rsplit(".", 1)[-1], node.name))
    assert callers == {("employees", "set_sign_in_name"), ("platform_account", "set_sign_in_name")}


# ── platform accounts ─────────────────────────────────────────────────────

def test_a_platform_account_sets_its_own(db):
    cog = _cog(groups=("surveyor",), username="test.surveyor")
    caller = {"id": cog.sub, "username": "test.surveyor", "cognito_groups": ["surveyor"]}
    with _aws(cog):
        out = P.set_sign_in_name(payload=P._SignInNameIn(sign_in_name="Surveys"), caller=caller, db=db)
    assert out == {"sign_in_name": "surveys"}
    (row,) = _audits(db, "account.sign_in_name_set")
    assert row.target_table == "cognito_users" and str(row.target_id) == cog.sub


def test_a_super_admin_clears_a_surveyors_name(db):
    cog = _cog(groups=("surveyor",), current="x")
    with patch.object(PA, "_resolve_account", return_value=("the.person", cog.sub)), _aws(cog), \
            patch("app.services.email_change.cognito_account",
                  return_value={"groups": {"surveyor"}, "sub": cog.sub}):
        out = PA.platform_clear_sign_in_name(account_id=uuid.UUID(cog.sub), _super={"id": "owner"}, db=db)
    assert out == {"cleared": True}
    assert _audits(db, "account.sign_in_name_cleared")[0].after_snapshot["cleared_by"] == "super_admin"


def test_a_super_admin_cannot_clear_a_company_account(db):
    cog = _cog(groups=("walker",), current="x")
    with patch.object(PA, "_resolve_account", return_value=("the.person", cog.sub)), _aws(cog), \
            patch("app.services.email_change.cognito_account",
                  return_value={"groups": {"walker"}, "sub": cog.sub}), pytest.raises(HTTPException) as exc:
        PA.platform_clear_sign_in_name(account_id=uuid.UUID(cog.sub), _super={"id": "owner"}, db=db)
    assert exc.value.status_code == 403 and not cog.admin_delete_user_attributes.called


def test_a_super_admin_uses_my_account_for_their_own(db):
    me = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        PA.platform_clear_sign_in_name(account_id=uuid.UUID(me), _super={"id": me}, db=db)
    assert exc.value.status_code == 400


def test_a_super_admin_clears_a_surveyors_name_from_the_survey_page(db):
    from app.models.survey_register import SurveyContributor
    from app.routers import survey_register as SR
    from datetime import date
    SurveyContributor.__table__.create(bind=db.get_bind(), checkfirst=True)
    con = SurveyContributor(id=uuid.uuid4(), cognito_sub=str(uuid.uuid4()), display_name="S",
                            cognito_username="test.surveyor", agreement_version="1", agreement_signed_on=date.today())
    db.add(con); db.commit()
    cog = _cog(current="rude", username="test.surveyor")
    with _aws(cog):
        assert SR.clear_surveyor_sign_in_name(contributor_id=con.id, owner={"id": "owner"}, db=db) == {"cleared": True}
    assert cog.admin_delete_user_attributes.call_args.kwargs["Username"] == "test.surveyor"
    (row,) = _audits(db, "account.sign_in_name_cleared")
    assert row.target_table == "survey_contributors" and row.after_snapshot["cleared_by"] == "super_admin"
