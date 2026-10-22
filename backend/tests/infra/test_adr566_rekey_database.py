"""The database follows its accounts into the new Cognito pool (ADR-566 D3).

backend/scripts/cognito_rekey_database.py rewrites every column that stores a
Cognito sub. The first draft of the plan named five; the schema has twelve,
four of which decide whether a surveyor owns their own data (writer_sub). So
the script walks the schema rather than trusting its list, and these tests pin
both the walk and the rewrite.
"""
import importlib.util
import pathlib
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.company import Company
from app.models.employee import Employee
from tests.conftest import SEED_COMPANY_ID, sqlite_mirror_with_defaults

_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "cognito_rekey_database.py"
_spec = importlib.util.spec_from_file_location("cognito_rekey_database", _PATH)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

OLD, NEW = "us-east-2_OLDPOOL", "us-east-2_NEWPOOL"


MIRRORS = {}


@pytest.fixture(autouse=True)
def _tables(db):
    """The shared test schema is targeted, and SQLite can't create JSONB: create
    a mirror of every table the re-key touches that the schema lacks."""
    from sqlalchemy import inspect as sa_inspect
    have = set(sa_inspect(db.get_bind()).get_table_names())
    for name in sorted({t for (t, _c) in R.REKEY} - have):
        MIRRORS[name] = sqlite_mirror_with_defaults(Base.metadata.tables[name])
        MIRRORS[name].create(bind=db.get_bind(), checkfirst=True)
    yield


def _cog(emails: dict):
    c = MagicMock()
    c.admin_get_user.side_effect = lambda UserPoolId, Username: {
        "Username": Username, "UserAttributes": [{"Name": "email", "Value": emails[Username]}]}
    return c


def _world(db):
    from app.models.survey_register import SurveyContributor
    old_w, old_s, old_p = (str(uuid.uuid4()) for _ in range(3))
    emp = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="W", role="walker", is_active=True,
                   username="walker.test", cognito_sub=old_w, email="walker@test.com", account_status="active")
    con = SurveyContributor(id=uuid.uuid4(), cognito_sub=old_s, display_name="S", cognito_username="test.surveyor",
                            email="old-surveyor@example.com", agreement_version="1", agreement_signed_on=date.today())
    db.add_all([emp, con]); db.flush()
    walk = uuid.uuid4()
    db.execute(Base.metadata.tables["survey_walks"].insert().values(
        id=walk, writer_sub=old_s, block_key="Main_0", street="Main", addresses=[], source_dataset="x",
        fetched_at=datetime.now(timezone.utc), attest_off_shift=True, attest_unbranded=True,
        attest_as_self=True, started_at=datetime.now(timezone.utc)))
    bystander = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name="B", role="walker", is_active=True,
                         username="not.moved", cognito_sub="someone-else", email="b@example.com", account_status="active")
    db.add(bystander)
    company = db.query(Company).filter(Company.id == SEED_COMPANY_ID).one()
    company.machine_client_id = "old-bot-client"
    db.commit()
    mapping = [{"username": "walker.test", "old_sub": old_w, "new_sub": str(uuid.uuid4())},
               {"username": "test.surveyor", "old_sub": old_s, "new_sub": str(uuid.uuid4())},
               {"username": "adon", "old_sub": old_p, "new_sub": str(uuid.uuid4())},
               {"username": "test.platform_support", "old_sub": None, "new_sub": str(uuid.uuid4())}]
    emails = {"walker.test": "owner+walker@example.com", "test.surveyor": "owner+surveyor@example.com",
              "adon": "owner@example.com", "test.platform_support": "owner+platform_support@example.com"}
    return mapping, emails, emp, con, walk, bystander


def test_the_schema_walk_finds_every_sub_column_today():
    assert R.unhandled_columns() == []


def test_a_sub_column_missing_from_the_list_stops_the_run(monkeypatch):
    """Probe: drop one ownership column from REKEY; the walk must catch it."""
    monkeypatch.delitem(R.REKEY, ("survey_walks", "writer_sub"))
    assert ("survey_walks", "writer_sub") in R.unhandled_columns()
    with pytest.raises(SystemExit) as exc:
        R.check_schema()
    assert "survey_walks" in str(exc.value)


def test_a_dry_run_counts_and_changes_nothing(db):
    mapping, emails, emp, con, walk, _ = _world(db)
    provision = MagicMock()
    out = R.run(db, mapping, OLD, NEW, apply=False, cog=_cog(emails), provision=provision)
    assert out["rows"]["employees.cognito_sub"] == 1
    assert out["rows"]["survey_contributors.cognito_sub"] == 1
    assert out["rows"]["survey_walks.writer_sub"] == 1
    assert out["unmatched"] == ["adon"] and out["bot_clients"] == 1
    db.expire_all()
    assert emp.cognito_sub == mapping[0]["old_sub"] and not provision.called


def test_apply_rekeys_mirrors_reprovisions_and_audits_once(db):
    from app.models.survey_register import SurveyContributor
    mapping, emails, emp, con, walk, bystander = _world(db)
    provision = MagicMock(return_value=("new-bot-client", "secret"))
    out = R.run(db, mapping, OLD, NEW, apply=True, cog=_cog(emails), provision=provision)
    db.expire_all()
    e = db.get(Employee, emp.id); c = db.get(SurveyContributor, con.id)
    walks = Base.metadata.tables["survey_walks"]
    writer = db.execute(walks.select().with_only_columns(walks.c.writer_sub).where(walks.c.id == walk)).scalar()
    assert e.cognito_sub == mapping[0]["new_sub"] and e.email == "owner+walker@example.com"
    assert c.cognito_sub == mapping[1]["new_sub"] and c.email == "owner+surveyor@example.com"
    assert writer == mapping[1]["new_sub"], "the surveyor must still own their walk"
    assert db.get(Employee, bystander.id).cognito_sub == "someone-else"
    assert db.query(Company).filter(Company.id == SEED_COMPANY_ID).one().machine_client_id == "new-bot-client"
    provision.assert_called_once()
    (row,) = db.query(AuditLog).filter(AuditLog.action_type == "cognito.pool_migrated").all()
    d = row.after_snapshot
    assert d["old_pool"] == OLD and d["new_pool"] == NEW and d["accounts"] == 3 and d["truncated"] is False
    assert d["bot_clients"] == [{"company_id": str(SEED_COMPANY_ID), "old": "old-bot-client", "new": "new-bot-client"}]
    assert "@" not in str(d), "the audit row must not carry an address"
    assert out["emails_mirrored"] == 2


def test_the_audit_target_is_a_stable_uuid_for_the_pool(db):
    mapping, emails, *_ = _world(db)
    R.run(db, mapping, OLD, NEW, apply=True, cog=_cog(emails), provision=MagicMock(return_value=("n", "s")))
    row = db.query(AuditLog).filter(AuditLog.action_type == "cognito.pool_migrated").one()
    assert str(row.target_id) == str(uuid.uuid5(uuid.NAMESPACE_URL, f"cognito-idp:{NEW}"))
