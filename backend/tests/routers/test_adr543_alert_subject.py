"""Every account alert names the account (ADR-543 D2/D3).

Owner, 2026-10-19: "Mfa.Privileged Unprotected" -- critical, 42 occurrences --
named neither the account nor whether it was platform staff. The cause was a
false alarm (the asheflow.bot row, fixed by ADR-539 D3), but an alert that
cannot say who it is about cannot be acted on, and its (type, company) dedup
would merge two real accounts into one.
"""
import ast
import pathlib

from app.models.platform_alert import PlatformAlert
from app.routers import platform_alerts as PA
from app.services.integration_alerts import raise_platform_alert
from tests.conftest import SEED_COMPANY_ID

import pytest

T = "mfa.privileged_unprotected"


@pytest.fixture(autouse=True)
def _platform_alerts_table(db):
    """conftest's db builds a fixed table list without platform_alerts (the
    same fixture ADR-535's tests use)."""
    PlatformAlert.__table__.create(bind=db.get_bind(), checkfirst=True)
    db.query(PlatformAlert).delete(); db.commit()   # the table outlives the db fixture's cleanup
    yield
    db.rollback(); db.query(PlatformAlert).delete(); db.commit()


def _raise(db, ref, kind="employee", role="admin", company=SEED_COMPANY_ID):
    raise_platform_alert(db, alert_type=T, company_id=company, message="m", severity="critical",
                         subject_kind=kind, subject_ref=ref, subject_role=role)
    db.commit()


def _open(db):
    return db.query(PlatformAlert).filter(PlatformAlert.alert_type == T,
                                          PlatformAlert.is_resolved.is_(False)).all()


class TestOneAlertPerAccount:
    def test_two_accounts_are_two_alerts(self, db):
        _raise(db, "pass.check")
        _raise(db, "test.user")
        assert sorted(a.subject_ref for a in _open(db)) == ["pass.check", "test.user"]

    def test_the_same_account_again_is_one_alert_counted_twice(self, db):
        _raise(db, "pass.check")
        _raise(db, "pass.check")
        [a] = _open(db)
        assert a.occurrence_count == 2

    def test_an_infrastructure_alert_still_dedups_without_a_subject(self, db):
        for _ in range(2):
            raise_platform_alert(db, alert_type="email_delivery_failed", company_id=None, message="m")
            db.commit()
        [a] = db.query(PlatformAlert).filter(PlatformAlert.alert_type == "email_delivery_failed").all()
        assert a.occurrence_count == 2 and a.subject_ref is None

    def test_a_platform_account_is_recorded_as_platform_staff(self, db):
        _raise(db, "adon", kind="platform", role="super_admin", company=None)
        [a] = _open(db)
        assert (a.subject_kind, a.subject_ref, a.subject_role, a.company_id) == ("platform", "adon", "super_admin", None)


class TestWhoSeesTheHandle:
    def _list(self, db, groups):
        return PA.list_platform_alerts(include_resolved=False, limit=100,
                                       _super={"cognito_groups": groups}, db=db)

    def test_a_super_admin_sees_the_account(self, db):
        _raise(db, "pass.check")
        [a] = self._list(db, ["super_admin"])
        assert a.subject_ref == "pass.check" and a.subject_role == "admin"

    def test_platform_support_sees_the_role_not_the_account(self, db):
        """ADR-343 D4: a cross-tenant login sees no personal identifiers."""
        _raise(db, "pass.check")
        [a] = self._list(db, ["platform_support"])
        assert a.subject_ref is None
        assert (a.subject_kind, a.subject_role) == ("employee", "admin")


def test_the_device_sweep_names_the_account_on_both_paths():
    """Both raise sites (employee rows and platform accounts) pass a subject."""
    src = pathlib.Path(__file__).resolve().parents[2] / "app/tasks/device_sweep.py"
    calls = [n for n in ast.walk(ast.parse(src.read_text()))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "raise_platform_alert"]
    assert len(calls) == 2
    for c in calls:
        kws = {k.arg for k in c.keywords}
        assert {"subject_kind", "subject_ref", "subject_role"} <= kws, kws


def test_the_migration_matches_the_model():
    mig = next((pathlib.Path(__file__).resolve().parents[2] / "alembic/versions").glob("*_adr543_platform_alert_subject.py"))
    text = mig.read_text()
    for col, typ in (("subject_kind", "String(16)"), ("subject_ref", "String(128)"), ("subject_role", "String(32)")):
        assert f'"{col}", sa.{typ}, nullable=True' in text
        assert getattr(PlatformAlert, col).type.length == int(typ.split("(")[1].rstrip(")"))
    assert '["alert_type", "company_id", "subject_ref"]' in text
