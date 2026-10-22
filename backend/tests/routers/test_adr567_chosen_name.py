"""A person's chosen name is shown everywhere; the legal name stays the record (ADR-567).

`Employee.name` is a hybrid: it reads the chosen name if set, else the legal
name; it writes the legal name; in a query it is COALESCE(chosen, legal).
Stored copies (`*_by_name`) keep the legal name and are swapped to the shown
name as they load. The legal name reaches only the person, management and
admin.
"""
import ast
import inspect
import pathlib
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from app.models.audit_log import AuditLog
from app.models.collection import CollectionToken
from app.models.employee import Employee
from app.routers import employees as E
from app.services import account_security, chosen_names
from tests.conftest import SEED_COMPANY_ID, sqlite_mirror_with_defaults

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


class _Redis:
    def __init__(self): self.d = {}
    def incr(self, k): self.d[k] = int(self.d.get(k, 0)) + 1; return self.d[k]
    def expire(self, k, ttl): pass


@pytest.fixture(autouse=True)
def _aws():
    cog = MagicMock()
    with patch.object(account_security, "_cognito", return_value=cog), \
         patch.object(account_security, "_redis", return_value=_Redis()):
        yield cog


def _emp(db, name="Legal Person", role="walker", chosen=None, username=None, company=SEED_COMPANY_ID):
    e = Employee(id=uuid.uuid4(), company_id=company, name=name, role=role, is_active=True,
                 username=username or f"{uuid.uuid4().hex[:8]}.x", account_status="active")
    e.chosen_name = chosen
    db.add(e); db.commit()
    return e


# ── the hybrid ────────────────────────────────────────────────────────────

def test_name_reads_the_chosen_name_and_writes_the_legal_one(db):
    e = _emp(db, name="Legal Person", chosen="Sam")
    assert e.name == "Sam" and e.legal_name == "Legal Person"
    e.name = "Corrected Legal"          # what ADP sync and an admin edit do
    db.commit(); db.refresh(e)
    assert e.legal_name == "Corrected Legal" and e.chosen_name == "Sam" and e.name == "Sam"


def test_without_a_chosen_name_the_legal_name_is_the_name(db):
    e = _emp(db, name="Only Name")
    assert e.name == "Only Name" == e.legal_name


def test_queries_search_and_sort_by_the_shown_name(db):
    a = _emp(db, name="Zed Legal", chosen="Alex")
    b = _emp(db, name="Bea Legal")
    rows = (db.query(Employee.id, Employee.name)
            .filter(Employee.id.in_([a.id, b.id])).order_by(Employee.name).all())
    assert [r.name for r in rows] == ["Alex", "Bea Legal"], "row.name and order_by use the shown name"
    assert db.query(Employee).filter(Employee.name.ilike("alex")).one().id == a.id
    assert db.query(Employee).filter(Employee.name.ilike("zed legal")).count() == 0, \
        "searching the legal name doesn't find someone by it"


# ── past records ──────────────────────────────────────────────────────────

def test_a_stored_copy_shows_the_chosen_name_and_keeps_the_legal_one(db):
    sqlite_mirror_with_defaults(CollectionToken.__table__).create(bind=db.get_bind(), checkfirst=True)
    e = _emp(db, name="Legal Person", role="admin")
    tok = CollectionToken(id=uuid.uuid4(), scope="company", dataset="addresses", company_id=SEED_COMPANY_ID,
                          token=uuid.uuid4().hex, label="x", daily_cap=5, created_by=e.id,
                          created_by_name=e.legal_name)
    db.add(tok); db.commit()
    tok_id = tok.id
    e.chosen_name = "Sam"; db.commit()
    db.expunge_all(); chosen_names.forget(db)
    loaded = db.query(CollectionToken).filter(CollectionToken.id == tok_id).one()
    assert loaded.created_by_name == "Sam"
    loaded.label = "touched"; db.commit()          # an unrelated write must not flush the swap
    stored = db.execute(text("select created_by_name from collection_tokens")).scalars().all()
    assert stored == ["Legal Person"], "the record keeps the legal name"


def test_every_stored_copy_writer_writes_the_legal_name():
    """ADR-567 D4: a constructor of a registered model, or an assignment to a
    registered name column, never stores `.name` (the shown name)."""
    import app.main  # noqa: F401
    from app.services.employee_redaction import REGISTRY
    models = {}
    for m, _f, n in REGISTRY:
        models.setdefault(m.__name__, set()).add(n)
    attrs = set().union(*models.values())
    bad = []
    for path in sorted(APP.rglob("*.py")):
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call):
                fname = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                for k in n.keywords if fname in models else []:
                    if k.arg in models[fname] and ".name" in ast.unparse(k.value):
                        bad.append(f"{path.name}:{k.value.lineno} {fname}({k.arg}=...)")
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Attribute) and t.attr in attrs and ".name" in ast.unparse(n.value):
                        bad.append(f"{path.name}:{n.lineno} {ast.unparse(t)} = ...")
    bad = [b for b in bad if "legal_name" not in b]
    assert not bad, f"stored copies must keep the legal name (use .legal_name): {bad}"


# ── setting it ────────────────────────────────────────────────────────────

class TestSettingIt:
    def test_the_person_sets_it_and_the_audit_never_holds_the_legal_name(self, db, _aws):
        e = _emp(db, name="Legal Person", username="legal.person")
        out = E.set_chosen_name(payload=E._ChosenNameIn(chosen_name="  Sam   Rivera "), caller=e, db=db)
        assert out.name == "Sam Rivera" and out.chosen_name == "Sam Rivera" and out.legal_name == "Legal Person"
        (row,) = db.query(AuditLog).filter(AuditLog.action_type == "account.chosen_name_set").all()
        assert row.after_snapshot == {"from": None, "to": "Sam Rivera", "by": "self"}
        assert "Legal Person" not in str(row.after_snapshot)
        kw = _aws.admin_update_user_attributes.call_args.kwargs
        assert kw["Username"] == "legal.person" and kw["UserAttributes"] == [{"Name": "name", "Value": "Sam Rivera"}]

    @pytest.mark.parametrize("bad", ["=HYPERLINK(1)", "-Jo", "@sam", "Sam2", "a" * 101])
    def test_a_bad_name_is_refused(self, db, bad):
        e = _emp(db)
        with pytest.raises(HTTPException) as exc:
            E.set_chosen_name(payload=E._ChosenNameIn(chosen_name=bad[:200]), caller=e, db=db)
        assert exc.value.status_code == 422 and e.chosen_name is None

    def test_the_legal_name_typed_as_a_chosen_name_stores_nothing(self, db):
        e = _emp(db, name="Legal Person")
        E.set_chosen_name(payload=E._ChosenNameIn(chosen_name="Legal Person"), caller=e, db=db)
        assert e.chosen_name is None

    def test_clearing_your_own(self, db):
        e = _emp(db, chosen="Sam")
        out = E.clear_own_chosen_name(caller=e, db=db)
        assert out.chosen_name is None and out.name == out.legal_name
        assert db.query(AuditLog).filter(AuditLog.action_type == "account.chosen_name_cleared").count() == 1

    def test_the_request_body_is_bounded(self):
        with pytest.raises(ValidationError):
            E._ChosenNameIn(chosen_name="Sam", extra=1)
        with pytest.raises(ValidationError):
            E._ChosenNameIn(chosen_name="")


class TestAnAdminClearsNeverSets:
    def test_an_admin_clears_one_in_their_company(self, db):
        admin, target = _emp(db, role="admin"), _emp(db, chosen="Rude Name")
        assert E.admin_clear_chosen_name(employee_id=target.id, db=db, caller=admin,
                                         current_user={"cognito_groups": ["admin"]}) == {"cleared": True}
        db.refresh(target)
        assert target.chosen_name is None

    def test_another_company_is_not_found(self, db):
        admin, other = _emp(db, role="admin"), _emp(db, chosen="X Y", company=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            E.admin_clear_chosen_name(employee_id=other.id, db=db, caller=admin,
                                      current_user={"cognito_groups": ["admin"]})
        assert exc.value.status_code == 404

    def test_management_cannot_clear_an_admins(self, db):
        mgr, target = _emp(db, role="management"), _emp(db, role="admin", chosen="X Y")
        with pytest.raises(HTTPException) as exc:
            E.admin_clear_chosen_name(employee_id=target.id, db=db, caller=mgr,
                                      current_user={"cognito_groups": ["management"]})
        assert exc.value.status_code == 403

    def test_no_endpoint_lets_anyone_else_set_it(self):
        """Only set_chosen_name assigns a non-None chosen_name in the routers."""
        setters = []
        for path in sorted((APP / "routers").glob("*.py")):
            for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(fn, ast.FunctionDef):
                    for n in ast.walk(fn):
                        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "chosen_name"
                                                               for t in n.targets)
                                and ast.unparse(n.value) != "None"):
                            setters.append(f"{path.name}::{fn.name}")
        assert setters == ["employees.py::set_chosen_name"]


# ── who sees the legal name ───────────────────────────────────────────────

class TestTheLegalNamePartition:
    def _list(self, db, role):
        caller = _emp(db, role=role, name=f"Caller {role}")
        _emp(db, name="Legal Person", chosen="Sam")
        pg = MagicMock(); pg.apply = lambda q: q
        return E.get_all_employees(caller=caller, pg=pg, include_inactive=False, db=db)

    @pytest.mark.parametrize("role", ["admin", "management"])
    def test_management_and_admin_see_it(self, db, role):
        rows = self._list(db, role)
        sam = next(r for r in rows if r.name == "Sam")
        assert getattr(sam, "legal_name", None) == "Legal Person"

    def test_dispatch_sees_only_the_shown_name_and_no_username(self, db):
        rows = self._list(db, "dispatch")
        sam = next(r for r in rows if r.name == "Sam")
        assert not hasattr(sam, "legal_name") and sam.username is None
        assert "Legal Person" not in sam.model_dump_json()

    def test_field_staff_see_only_the_shown_name(self, db):
        rows = self._list(db, "walker")
        sam = next(r for r in rows if r.name == "Sam")
        assert "Legal Person" not in sam.model_dump_json()

    def test_legal_name_is_on_one_response_model_only(self):
        """ADR-483: walk every response model the app defines; legal_name lives
        on EmployeeRecordResponse (and nothing else)."""
        import app.main  # noqa: F401
        seen = set()
        def walk(cls):
            for sub in cls.__subclasses__():
                if sub not in seen:
                    seen.add(sub); walk(sub)
        walk(BaseModel)
        holders = sorted(f"{c.__module__}.{c.__name__}" for c in seen
                         if c.__module__.startswith("app.") and "legal_name" in getattr(c, "model_fields", {}))
        assert holders == ["app.schemas.employee.EmployeeRecordResponse"], holders


# ── the other readers of the legal name ───────────────────────────────────

def test_redaction_clears_the_chosen_name_too(db):
    """The employee row's own scrub; the copies are the redaction suite's job."""
    from app.services import employee_redaction as R
    e = _emp(db, name="Legal Person", chosen="Sam")
    with patch.object(R, "REGISTRY", []):
        R.redact_employee_names(db, e.id)
    db.commit(); db.refresh(e)
    REDACTED_NAME = R.REDACTED_NAME
    assert e.legal_name == REDACTED_NAME and e.chosen_name is None and e.name == REDACTED_NAME


def test_campaign_redaction_hides_both_names(db):
    from app.tasks.campaign_redaction import _name_patterns
    e = _emp(db, name="Legal Person", chosen="Sam Rivera")
    pats = _name_patterns([e])
    def scrub(t):
        for p, r in pats: t = p.sub(r, t)
        return t
    assert "Sam Rivera" not in scrub("Sam Rivera was late") and "Legal Person" not in scrub("Legal Person helped")


def test_a_machine_caller_has_a_legal_name():
    from app.api.deps import MachineCaller
    assert MachineCaller(id="bot", company_id=uuid.uuid4(), name="asheflow.bot").legal_name == "asheflow.bot"


# ── the legal name can't be overwritten (owner, 2026-10-22) ──────────────

class TestTheLegalNameIsGuarded:
    """Where ADP is connected only ADP changes the legal name; elsewhere
    management/admin may correct it, recorded with the value before. And an
    edit that sends back the shown (chosen) name never becomes the legal name."""

    @pytest.fixture(autouse=True)
    def _adp_table(self, db):
        from app.models.adp_integration import ADPIntegration
        ADPIntegration.__table__.create(bind=db.get_bind(), checkfirst=True)

    def _edit(self, db, target, name, caller):
        from app.schemas.employee import EmployeeUpdate
        with patch.object(E, "_cognito_client", return_value=MagicMock()):
            return E.update_employee(employee_id=target.id, employee=EmployeeUpdate(name=name), db=db,
                                     caller=caller, current_user={"cognito_groups": [caller.role]})

    def _connect_adp(self, db):
        from app.models.adp_integration import ADPIntegration
        db.add(ADPIntegration(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, adp_client_id="c",
                              adp_client_secret_arn="arn:s", adp_certificate_arn="arn:c", is_enabled=True))
        db.commit()

    def test_with_adp_connected_an_edit_cannot_change_it(self, db):
        self._connect_adp(db)
        admin, target = _emp(db, role="admin"), _emp(db, name="Legal Person")
        with pytest.raises(HTTPException) as exc:
            self._edit(db, target, "Someone Else", admin)
        assert exc.value.status_code == 409 and "ADP" in exc.value.detail
        db.refresh(target)
        assert target.legal_name == "Legal Person"

    def test_without_adp_a_correction_is_recorded_with_the_old_name(self, db):
        admin, target = _emp(db, role="admin"), _emp(db, name="Legal Persn")
        self._edit(db, target, "Legal Person", admin)
        db.refresh(target)
        assert target.legal_name == "Legal Person"
        row = db.query(AuditLog).filter(AuditLog.action_type == "employee.update").one()
        assert row.after_snapshot["legal_name_before"] == "Legal Persn"

    def test_the_chosen_name_sent_back_never_becomes_the_legal_name(self, db):
        admin, target = _emp(db, role="admin"), _emp(db, name="Legal Person", chosen="Sam")
        self._edit(db, target, "Sam", admin)          # an old form round-tripping `name`
        db.refresh(target)
        assert target.legal_name == "Legal Person" and target.chosen_name == "Sam"

    def test_adp_sync_still_writes_it(self, db):
        """The sync assigns `employee.name`, which writes the legal name."""
        src = (APP / "tasks" / "adp_sync.py").read_text(encoding="utf-8")
        assert 'employee.name = worker["person"]["legalName"]["formattedName"]' in src
        e = _emp(db, name="Old Legal", chosen="Sam")
        e.name = "New Legal From ADP"; db.commit(); db.refresh(e)
        assert e.legal_name == "New Legal From ADP" and e.chosen_name == "Sam"
