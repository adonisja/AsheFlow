"""ADR-289 — operating_mode guards and the RequireMode gate.

The NEGATIVE tests matter most here and are the reason this file exists:

  - a company admin must NOT be able to set the mode
  - the generic super-admin config PATCH must NOT be able to set it either
    (the bypass: it calls _apply_config_update(..., allow_super_admin_fields=True),
    which sets any field on the payload with none of the dedicated endpoint's guards)
  - a flip must be REFUSED while work is in flight, because a warning protects the
    operator and only a refusal protects the walker mid-route

Each assertion checks state AFTER the call, not just the status code — a guard that
returns the right error while still writing is the failure this is here to catch.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import RequireMode
from app.models.company import Company, CompanyConfig
from app.routers.companies import (
    CompanyConfigUpdate,
    OperatingModeUpdate,
    _GUARDED_FIELDS,
    _apply_config_update,
)
from app.services.constants import MODE_FULL, MODE_WORKFORCE


# ── request schema (dim 9) ────────────────────────────────────────────────────

def test_mode_payload_rejects_unknown_keys():
    """extra='forbid' — an unrecognised key is a client bug worth a 422."""
    with pytest.raises(Exception):
        OperatingModeUpdate(operating_mode="full", confirm_slug="x", bogus=1)


def test_mode_payload_rejects_invalid_mode():
    """Literal, not a free string — 'banana' must never reach the DB."""
    with pytest.raises(Exception):
        OperatingModeUpdate(operating_mode="banana", confirm_slug="x")


def test_mode_payload_requires_confirmation_slug():
    with pytest.raises(Exception):
        OperatingModeUpdate(operating_mode="full")


# ── the field is not settable through either config PATCH ─────────────────────

def test_operating_mode_is_a_guarded_field():
    assert "operating_mode" in _GUARDED_FIELDS


def test_config_update_schema_does_not_expose_operating_mode():
    """The first line of defence: the field is not on the update schema at all,
    so Pydantic drops it before _apply_config_update ever sees it.

    _GUARDED_FIELDS is defence-in-depth behind this. If someone later adds
    operating_mode to CompanyConfigUpdate (to surface it in a form, say), this test
    fails and points at the guard that must then do the work.
    """
    assert "operating_mode" not in CompanyConfigUpdate.model_fields


def test_guarded_field_refused_even_for_super_admin(db):
    """THE BYPASS. The generic super-admin PATCH passes allow_super_admin_fields=True,
    which sets any field on the payload. _GUARDED_FIELDS must refuse regardless.

    Simulated by injecting the field into the dumped payload, because the schema does
    not carry it — this asserts the guard itself, not the schema's omission.
    """
    class _Payload:
        @staticmethod
        def model_dump(exclude_unset=True):
            return {"operating_mode": MODE_FULL}

    config = db.query(CompanyConfig).first()
    before = config.operating_mode

    with pytest.raises(HTTPException) as exc:
        _apply_config_update(config, _Payload(), allow_super_admin_fields=True)

    assert exc.value.status_code == 400
    assert config.operating_mode == before, "guard raised but still mutated the config"


# ── the model column (dim 3) ──────────────────────────────────────────────────

def test_config_rows_always_have_a_mode(db):
    """nullable=False with a server_default: a row created without the field must
    still come back with a usable value, never None.

    A null mode cannot distinguish 'new company' from 'config lost' — the ADR-283
    failure this column exists to avoid.
    """
    config = db.query(CompanyConfig).first()
    assert config.operating_mode in (MODE_FULL, MODE_WORKFORCE)


# ── RequireMode (dim 2) ───────────────────────────────────────────────────────

def _company_with_mode(db, mode: str) -> Company:
    company = Company(id=uuid.uuid4(), name=f"Co {mode}", slug=f"co-{mode}", is_active=True)
    db.add(company)
    db.flush()
    db.add(CompanyConfig(
        id=uuid.uuid4(), company_id=company.id, is_configured=True, operating_mode=mode,
    ))
    db.commit()
    return company


def test_require_mode_allows_matching_mode(db, monkeypatch):
    company = _company_with_mode(db, MODE_FULL)
    emp = type("E", (), {"company_id": company.id})()
    monkeypatch.setattr(
        "app.api.deps._resolve_employee_from_cognito", lambda user, session: (emp, "sub")
    )
    # No exception == allowed.
    RequireMode(MODE_FULL)(current_user={"cognito_groups": []}, db=db)


def test_require_mode_returns_404_not_403(db, monkeypatch):
    """404, not 403. A 403 says 'this exists and you may not have it', which invites
    retries and leaks the shape of the product to a tenant who will never have it."""
    company = _company_with_mode(db, MODE_WORKFORCE)
    emp = type("E", (), {"company_id": company.id})()
    monkeypatch.setattr(
        "app.api.deps._resolve_employee_from_cognito", lambda user, session: (emp, "sub")
    )
    with pytest.raises(HTTPException) as exc:
        RequireMode(MODE_FULL)(current_user={"cognito_groups": []}, db=db)
    assert exc.value.status_code == 404


def test_require_mode_treats_missing_config_as_not_having_the_feature(db, monkeypatch):
    """The safe direction. Assuming 'full' would expose the package pipeline to a
    tenant whose configuration never said so."""
    company = Company(id=uuid.uuid4(), name="No Config", slug="no-config", is_active=True)
    db.add(company)
    db.commit()
    emp = type("E", (), {"company_id": company.id})()
    monkeypatch.setattr(
        "app.api.deps._resolve_employee_from_cognito", lambda user, session: (emp, "sub")
    )
    with pytest.raises(HTTPException) as exc:
        RequireMode(MODE_FULL)(current_user={"cognito_groups": []}, db=db)
    assert exc.value.status_code == 404


def test_super_admin_bypasses_the_gate(db):
    """A platform operator must be able to inspect a workforce tenant's endpoints.
    Super admins have no Employee row, so this must not fall through to the lookup."""
    RequireMode(MODE_FULL)(current_user={"cognito_groups": ["super_admin"]}, db=db)


# ── background-task scoping (ADR-293) ─────────────────────────────────────────

def test_full_mode_company_ids_excludes_workforce_tenants(db):
    from app.services.company_config import full_mode_company_ids

    full = _company_with_mode(db, MODE_FULL)
    workforce = _company_with_mode(db, MODE_WORKFORCE)

    ids = full_mode_company_ids(db)
    assert full.id in ids
    assert workforce.id not in ids, "decay/rollup would run against a workforce tenant"


# ── in-flight blockers (ADR-289 D1c(ii)) ──────────────────────────────────────
# Own engine: Route/TruckZone are not in the shared conftest fixture, and TruckZone
# uses JSONB, which SQLite cannot compile — so those columns are swapped for JSON the
# same way conftest handles graduation_quizzes.

@pytest.fixture
def flip_db():
    from sqlalchemy import create_engine, MetaData
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import JSON as GenericJSON, Text
    from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    from app.models.employee import Employee
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment
    from app.models.truck_zone import TruckZone
    from app.models.walker_route import Route, RouteParticipant

    meta = MetaData()
    for table in (
        Company.__table__, CompanyConfig.__table__, Employee.__table__,
        Truck.__table__, TruckAssignment.__table__,
        Route.__table__, RouteParticipant.__table__, TruckZone.__table__,
    ):
        copied = table.to_metadata(meta)
        for col in copied.columns:
            # SQLite compiles neither JSONB nor ARRAY. Swap both for JSON so the
            # tables can be created; these tests never read those columns.
            if isinstance(col.type, JSONB):
                col.type = SQLiteJSON()
            elif isinstance(col.type, ARRAY):
                col.type = GenericJSON()

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


# Routes are inserted with raw SQL: the ORM mapper binds the real ARRAY type even
# against the shimmed table copy, and SQLite's driver cannot bind a Python list.
# These tests only need the ROWS to exist for the blocker COUNT queries.
_EMPTY_ARRAYS = "'[]'"


def _insert_route(db, company_id, truck_assignment_id, *, status, returned_at=None):
    import datetime as dt
    from sqlalchemy import text
    db.execute(text(
        "INSERT INTO routes (id, company_id, truck_assignment_id, route_date, "
        "route_number, block_keys, segment_ids, tote_ids, tba_numbers, "
        "normalised_addresses, package_count, slot_cost, capacity_limit, "
        "effort_class, workload_source, phase4_solo_opted_in, wave_number, "
        "status, returned_at) VALUES (:id, :cid, :ta, :d, 1, '[]', '[]', '[]', "
        "'[]', '[]', 0, 0, 12, 'standard', 'default', 0, 1, :st, :ret)"
    ), {
        "id": uuid.uuid4().hex, "cid": company_id.hex, "ta": truck_assignment_id.hex,
        "d": dt.date.today().isoformat(), "st": status,
        "ret": returned_at.isoformat() if returned_at else None,
    })
    db.commit()


def _tenant(db, slug="flip-co"):
    cid = uuid.uuid4()
    db.add(Company(id=cid, name="Flip Co", slug=slug, is_active=True,
                   timezone="America/New_York"))
    db.flush()
    db.add(CompanyConfig(id=uuid.uuid4(), company_id=cid, is_configured=True,
                         operating_mode=MODE_FULL))
    db.commit()
    return cid


def test_no_blockers_on_a_quiet_day(flip_db):
    from app.routers.companies import _mode_flip_blockers
    assert _mode_flip_blockers(flip_db, _tenant(flip_db)) == []


def test_a_route_still_out_blocks_the_flip(flip_db):
    """The reason this is a 409 and not a warning: a walker mid-route whose route
    endpoints start returning 404 cannot finish or report their day."""
    import datetime as dt
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment
    from app.routers.companies import _mode_flip_blockers

    cid = _tenant(flip_db)
    truck = Truck(id=uuid.uuid4(), company_id=cid, name="T1", is_active=True)
    flip_db.add(truck); flip_db.flush()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=cid, truck_id=truck.id,
                         date=dt.date.today())
    flip_db.add(ta); flip_db.flush()
    _insert_route(flip_db, cid, ta.id, status="in_progress")

    blockers = _mode_flip_blockers(flip_db, cid)
    assert blockers and "still out" in blockers[0]


def test_a_returned_route_does_not_block(flip_db):
    """Once the day is closed out the flip is safe — the guard must not be sticky."""
    import datetime as dt
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment
    from app.routers.companies import _mode_flip_blockers

    cid = _tenant(flip_db)
    truck = Truck(id=uuid.uuid4(), company_id=cid, name="T1", is_active=True)
    flip_db.add(truck); flip_db.flush()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=cid, truck_id=truck.id,
                         date=dt.date.today())
    flip_db.add(ta); flip_db.flush()
    _insert_route(flip_db, cid, ta.id, status="completed",
                  returned_at=dt.datetime.now(dt.timezone.utc))

    assert _mode_flip_blockers(flip_db, cid) == []


def test_blockers_do_not_leak_across_tenants(flip_db):
    """Dimension 1. Another company's live route must not block this company's flip."""
    import datetime as dt
    from app.models.truck import Truck
    from app.models.truck_assignment import TruckAssignment
    from app.routers.companies import _mode_flip_blockers

    busy = _tenant(flip_db, slug="busy-co")
    quiet = _tenant(flip_db, slug="quiet-co")

    truck = Truck(id=uuid.uuid4(), company_id=busy, name="T1", is_active=True)
    flip_db.add(truck); flip_db.flush()
    ta = TruckAssignment(id=uuid.uuid4(), company_id=busy, truck_id=truck.id,
                         date=dt.date.today())
    flip_db.add(ta); flip_db.flush()
    _insert_route(flip_db, busy, ta.id, status="in_progress")

    assert _mode_flip_blockers(flip_db, busy) != []
    assert _mode_flip_blockers(flip_db, quiet) == [], "cross-tenant leak in the flip guard"


# ── platform-level setting (ADR-289 D1a/D1b) ──────────────────────────────────
# These assert the SHAPE of the control, not one endpoint's behaviour: the mode is
# a platform decision, so it must be settable through exactly one super-admin route
# and by nothing else. They fail loudly if a later change quietly widens that.

def test_exactly_one_endpoint_accepts_operating_mode():
    """Grep-by-schema: any NEW request model exposing the field fails this test.

    Adding it to a tenant-facing schema is how a platform setting silently becomes a
    tenant one, and no individual endpoint's own tests would catch that.
    """
    import warnings
    warnings.filterwarnings("ignore")
    from app.main import app

    spec = app.openapi()
    writers = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method.lower() not in ("post", "patch", "put"):
                continue
            ref = (
                op.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
                .get("$ref", "")
            )
            schema = spec["components"]["schemas"].get(ref.split("/")[-1], {})
            if "operating_mode" in schema.get("properties", {}):
                writers.append(f"{method.upper()} {path}")

    assert writers == ["PATCH /api/v1/admin/companies/{company_id}/operating-mode"], (
        f"operating_mode is writable through unexpected endpoints: {writers}"
    )


def test_the_only_writer_is_super_admin_gated():
    import inspect
    from app.routers.companies import set_operating_mode

    deps = [
        getattr(p.default.dependency, "__name__", "")
        for p in inspect.signature(set_operating_mode).parameters.values()
        if getattr(p.default, "dependency", None) is not None
    ]
    assert "get_super_admin" in deps


def test_a_company_admin_cannot_pass_the_super_admin_gate():
    """A tenant `admin` is the most privileged COMPANY role and must still be refused:
    granting your own tenant a feature set is a platform decision, not a tenant one."""
    from app.api.deps import get_super_admin

    for groups in ([], ["admin"], ["management"], ["dispatch"]):
        with pytest.raises(HTTPException) as exc:
            get_super_admin(current_user={"cognito_groups": groups})
        assert exc.value.status_code == 403

    # Only the platform group passes.
    get_super_admin(current_user={"cognito_groups": ["super_admin"]})


def test_capabilities_is_readable_by_every_role():
    """Not role-gated on purpose: a walker's app builds its navigation from this, and
    a 403 here would leave field staff with a menu full of 404s."""
    import inspect
    from app.routers.companies import get_my_capabilities

    src = inspect.getsource(get_my_capabilities)
    for gate in ("RoleChecker", "allow_admin", "allow_oversight", "get_super_admin"):
        assert gate not in src, f"capabilities must not be gated by {gate}"
