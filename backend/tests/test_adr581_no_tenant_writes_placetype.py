"""ADR-581: no tenant-triggered code path writes PlaceType, and none may be added.

The owner (2026-10-23): "purge and delete all endpoints that attempt to write
data from any tenant back to our Library and pin tests to reject any future
attempts."

The walk below finds every place that COULD write the two PlaceType tables:
- a call to one of their writer functions;
- a construction of either model;
- a raw SQL string that inserts, updates or deletes either table.

It finds them across app/, backend/scripts/ and scripts/. Each must be on the
owner-only allowlist. The list is empty apart from the writer modules' own
internals until ADR-583's owner seed job is added, and that job must be added
here deliberately, with its ADR.
"""
import ast
import pathlib
import re
from types import SimpleNamespace

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SCAN_ROOTS = [BACKEND / "app", BACKEND / "scripts", REPO / "scripts"]

WRITER_FUNCS = {"upsert_building_geometry", "upsert_segments", "walk_connectors"}
MODELS = {"BuildingProfileLibrary", "StreetSegment"}
SQL_WRITE = re.compile(
    r"\b(insert\s+into|update|delete\s+from)\s+(building_profile_library|street_segments)\b", re.I)

# (path relative to the repo, enclosing function, what) that may write PlaceType.
# Owner-only. Adding an entry is a decision: cite its ADR beside it.
ALLOWED = {
    # segment_map owns street_segments; walk_connectors composes its own writer.
    ("backend/app/services/segment_map.py", "walk_connectors", "upsert_segments"),
    # ADR-583 D6: the owner's city seed, run as its own process with the writer
    # role (PLACETYPE_WRITER_URL), never from the API or Celery.
    ("backend/app/placetype/seed.py", "stage_addresspoint", "upsert_building_geometry"),
    ("backend/app/placetype/seed.py", "stage_geoclient", "upsert_building_geometry"),
    ("backend/app/placetype/seed.py", "stage_geoclient", "upsert_segments"),
    ("backend/app/placetype/seed.py", "stage_nodes", "walk_connectors"),
    # ADR-583 D4: the health check's write PROBE. Always rolled back; it exists
    # to prove the API's role is refused, and reports writable=true if not.
    ("backend/app/services/placetype_health.py", "_can_write", "raw SQL"),
}


def _python_files():
    for root in SCAN_ROOTS:
        if root.exists():
            yield from (p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _enclosing(tree):
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    def fn_of(node):
        while node in parent:
            node = parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"
    return fn_of


def _writes():
    found = []
    for path in _python_files():
        rel = str(path.relative_to(REPO))
        tree = ast.parse(path.read_text(), filename=rel)
        fn_of = _enclosing(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in WRITER_FUNCS or name in MODELS:
                    found.append((rel, fn_of(node), name, node.lineno))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_WRITE.search(node.value):
                found.append((rel, fn_of(node), "raw SQL", node.lineno))
    return found


def test_the_scan_sees_the_writers_it_is_guarding():
    """Vacuity guard: the walk must at least find the allowed internal call."""
    seen = {(f, fn, what) for f, fn, what, _ in _writes()}
    assert ("backend/app/services/segment_map.py", "walk_connectors", "upsert_segments") in seen


def test_no_write_to_placetype_outside_the_owner_allowlist():
    offenders = [w for w in _writes() if w[:3] not in ALLOWED]
    assert not offenders, (
        "These write PlaceType (building_profile_library / street_segments) outside the "
        f"owner-only allowlist: {offenders}. Tenants never write PlaceType (ADR-580, ADR-581). "
        "If this is an owner job, add it to ALLOWED with its ADR.")


def test_the_resolver_writes_nothing_on_a_miss(monkeypatch):
    """Behavioural: a miss returns the doors to pick from and leaves PlaceType
    alone. Since ADR-584 the resolver is door_resolver (PlaceType only); the
    GeoClient-backed address_resolver is deleted."""
    from app.services import door_resolver, place_geometry, segment_map

    def _boom(*a, **k):
        raise AssertionError("the resolver wrote PlaceType")
    monkeypatch.setattr(place_geometry, "upsert_building_geometry", _boom)
    monkeypatch.setattr(segment_map, "upsert_segments", _boom)
    monkeypatch.setattr(place_geometry, "door_with_segment", lambda db, b, a: None)
    monkeypatch.setattr(place_geometry, "doors_on_block", lambda db, b, a: [{"address": "350 5 AVE"}])
    monkeypatch.setattr(door_resolver, "_zip_map", lambda db: {})

    miss = door_resolver.resolve_door(object(), "352 5th Avenue", default_borough="1")
    assert isinstance(miss, door_resolver.Miss) and miss.near == [{"address": "350 5 AVE"}]
    assert not (BACKEND / "app/services/address_resolver.py").exists()


def test_the_library_router_and_promotion_are_gone():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert not [p for p in paths if "building-profile-library" in p]
    assert not (BACKEND / "app/routers/building_profile_library.py").exists()


def test_the_freeze_flag_and_exclusion_setting_are_gone():
    from app.core.config import settings
    assert not hasattr(settings, "library_sharing_enabled")
    assert not hasattr(settings, "survey_excluded_company_id")


class TestOpenCampaignsAreRetired:
    def test_the_assign_route_is_gone(self):
        from app.main import app
        assert not [p for p in app.openapi()["paths"] if p.endswith("/assign") and "collection" in p]

    def test_a_submission_to_an_open_token_is_refused(self):
        from fastapi import HTTPException
        from app.routers.collection import _authorise_scope
        with pytest.raises(HTTPException) as e:
            _authorise_scope(SimpleNamespace(scope="open", company_id=None), None)
        assert e.value.status_code == 410

    def test_a_super_admin_cannot_create_a_campaign(self):
        from fastapi import HTTPException
        from app.routers import collection
        body = SimpleNamespace(label="x", dataset="addresses", daily_cap=10, expires_in_days=None)
        with pytest.raises(HTTPException) as e:
            collection.create_token.__wrapped__(request=None, body=body, db=None,
                                                current_user={"cognito_groups": ["super_admin"]},
                                                caller=None)
        assert e.value.status_code == 403


def test_any_tenants_employee_is_refused_as_a_surveyor():
    """ADR-581 D10: one Employee row in any company refuses the survey write."""
    from fastapi import HTTPException
    from app.routers.survey_register import _assert_not_excluded

    class _Q:
        def filter(self, *a, **k):
            return self
        def first(self):
            return ("some-employee",)
    db = SimpleNamespace(query=lambda *a, **k: _Q())
    with pytest.raises(HTTPException) as e:
        _assert_not_excluded(db, "sub-of-another-dsps-employee")
    assert e.value.status_code == 403
