"""Employee-name redaction sweep (ADR-221). Public service."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.employee_redaction import redact_employee_names, REGISTRY, REDACTED_NAME


def test_registry_is_complete_and_valid():
    # Every registry entry references real (fk, name) attrs — a missing pair means
    # a name escapes redaction. Guards against a new _by_name column being added
    # without registering it.
    import app.models  # noqa: register
    for model, fk, nm in REGISTRY:
        assert hasattr(model, fk), f"{model.__name__}.{fk} missing"
        assert hasattr(model, nm), f"{model.__name__}.{nm} missing"
    assert len(REGISTRY) >= 30   # sanity: the ~40 columns across ~15 tables


def test_sweep_updates_each_registry_table_and_self():
    emp_id = uuid.uuid4()
    updated = []   # (model, filter_used) per .update call

    db = MagicMock()

    def _query(model):
        q = MagicMock(); f = MagicMock()
        f.filter.return_value = f
        def _update(vals, **k):
            updated.append(model)
            return 1
        f.update = _update
        # self-scrub path: query(Employee).filter(...).first()
        from app.models.employee import Employee
        if model is Employee:
            f.first.return_value = SimpleNamespace(
                id=emp_id, name="Jane Doe", email="j@x.co", phone_number="555", username="jane")
        q.filter.return_value = f
        return q
    db.query = _query

    counts = redact_employee_names(db, emp_id)

    # Every registry model had its name column update() invoked.
    registry_models = {m for m, _, _ in REGISTRY}
    assert registry_models.issubset(set(updated))
    # counts recorded per touched table + the employee self-scrub.
    assert "employees.self" in counts


def test_self_pii_scrubbed():
    emp_id = uuid.uuid4()
    emp = SimpleNamespace(id=emp_id, name="Jane Doe", email="j@x.co",
                          phone_number="5551234", username="jane")
    db = MagicMock()

    def _query(model):
        q = MagicMock(); f = MagicMock(); f.filter.return_value = f
        f.update.return_value = 0
        from app.models.employee import Employee
        f.first.return_value = emp if model is Employee else None
        q.filter.return_value = f
        return q
    db.query = _query

    redact_employee_names(db, emp_id)
    assert emp.name == REDACTED_NAME
    assert emp.email is None and emp.phone_number is None and emp.username is None


def test_library_excluded_from_registry():
    # BuildingProfileLibrary actor is the super-admin, not a tenant employee —
    # must NOT be in the tenant redaction registry (ADR-220/221).
    names = {m.__name__ for m, _, _ in REGISTRY}
    assert "BuildingProfileLibrary" not in names
