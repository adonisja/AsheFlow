"""No request schema may have an annotation that collapsed to NoneType.

THE BUG THIS CATCHES
--------------------
    from datetime import date

    class HubCreateRequest(BaseModel):
        truck_id: UUID
        date: Optional[date] = None      # <-- `date` here is the FIELD

The field name shadows the imported type inside the class body, so
`Optional[date]` resolves against the field being defined and the annotation
collapses to `NoneType`. Pydantic then rejects every real value with
"Input should be None", and the endpoint 422s for everyone.

Python raises nothing. The class builds, the module imports, `app.main` loads,
and the OpenAPI schema renders — it fails only when a client sends the field.
POST /dispatch/hubs and its publish sibling were both dead this way on staging.

The fix is an aliased import (`from datetime import date as _date_t`) so the
field can keep the name the API contract wants.
"""
import importlib
import pkgutil

from pydantic import BaseModel


def _all_models():
    seen = set()
    for mod in list(pkgutil.walk_packages(["app"], "app.")):
        try:
            m = importlib.import_module(mod.name)
        except Exception:
            continue  # optional/proprietary modules absent in some checkouts
        for obj in vars(m).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj not in seen
            ):
                seen.add(obj)
                yield obj


def test_no_field_annotation_collapsed_to_nonetype():
    """A NoneType annotation means the field accepts ONLY null.

    That is never intentional: a field that can only be None carries no data,
    so its presence in a schema means the annotation was shadowed.
    """
    offenders = []
    for model in _all_models():
        for name, field in getattr(model, "model_fields", {}).items():
            if field.annotation is type(None):
                offenders.append(f"{model.__module__}.{model.__name__}.{name}")

    assert not offenders, (
        "these schema fields accept ONLY null — the annotation was shadowed by "
        "the field name (see this module's docstring for the fix):\n    "
        + "\n    ".join(sorted(offenders))
    )


def test_hub_schemas_accept_a_real_date():
    """The specific regression, pinned by behaviour rather than by annotation.

    Asserting the parsed value — not just the type — is what proves the field
    is wired end to end; a shadowed annotation would raise here.
    """
    from datetime import date as real_date

    from app.routers.dispatch import HubCreateRequest, HubPublishRequest

    tid = "11111111-1111-1111-1111-111111111111"
    assert HubCreateRequest(truck_id=tid, date="2026-08-20").date == real_date(2026, 8, 20)
    assert HubPublishRequest(date="2026-08-20").date == real_date(2026, 8, 20)

    # And it stays optional — the handler falls back to company_today().
    assert HubCreateRequest(truck_id=tid).date is None
    assert HubPublishRequest().date is None
