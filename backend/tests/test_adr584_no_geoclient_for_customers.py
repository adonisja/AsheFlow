"""ADR-584 D3 — a customer's address never reaches GeoClient.

Walks every call site in app/ for the GeoClient entry points (and the base URL
and anchor helper that wrap them). Each must be on the allowlist below, which
names whose address it is. A new caller fails here until someone decides, in an
ADR, that it is not a customer's address.
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

ENTRY_POINTS = {"_geoclient_normalise", "_geoclient_intersection", "fetch_blockface",
                "walk_connectors", "_resolve_anchor_location", "_GEOCLIENT_BASE"}

# (file, enclosing function, name): whose address it is.
ALLOWED = {
    # The DSP's own staging points and zone corners (owner, 2026-10-24).
    ("app/routers/trucks.py", "_resolve_anchor_location", "_geoclient_normalise"),
    ("app/routers/trucks.py", "_resolve_anchor_location", "_geoclient_intersection"),
    ("app/routers/trucks.py", "set_truck_anchor", "_resolve_anchor_location"),
    ("app/routers/trucks.py", "set_truck_anchor2", "_resolve_anchor_location"),
    ("app/routers/anchor_points.py", "submit_anchor_point", "_resolve_anchor_location"),
    ("app/routers/anchor_points.py", "get_location_hints_for_truck", "_resolve_anchor_location"),
    ("app/routers/company_zones.py", "upsert_company_zone_from_streets", "_geoclient_intersection"),
    ("app/routers/company_zones.py", "upsert_company_zone_from_intersections", "_geoclient_intersection"),
    # The owner's survey (ADR-504), and the admin diagnostic.
    ("app/routers/survey_register.py", "survey_locate", "_geoclient_normalise"),
    ("app/routers/sort.py", "geoclient_probe", "_GEOCLIENT_BASE"),
    # The owner's city seed (ADR-583), and the topology module it drives.
    ("app/placetype/seed.py", "stage_nodes", "walk_connectors"),
    ("app/services/segment_map.py", "walk_connectors", "fetch_blockface"),
    ("app/services/segment_map.py", "fetch_blockface", "_GEOCLIENT_BASE"),
}


def _uses():
    found = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        rel = str(p.relative_to(BACKEND))
        tree = ast.parse(p.read_text())
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

        def fn_of(n):
            while n in parent:
                n = parent[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return n.name
            return "<module>"
        for n in ast.walk(tree):
            name = None
            if isinstance(n, ast.Call):
                name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            elif isinstance(n, ast.Name) and n.id == "_GEOCLIENT_BASE" and isinstance(n.ctx, ast.Load):
                name = n.id
            if name in ENTRY_POINTS:
                found.append((rel, fn_of(n), name, n.lineno))
    return found


def test_the_walk_sees_the_known_callers():
    """Vacuity guard: if the walk finds nothing, the next test passes forever."""
    seen = {u[:3] for u in _uses()}
    assert ("app/routers/trucks.py", "_resolve_anchor_location", "_geoclient_normalise") in seen
    assert ("app/routers/survey_register.py", "survey_locate", "_geoclient_normalise") in seen


def test_no_customer_address_reaches_geoclient():
    offenders = [u for u in _uses() if u[:3] not in ALLOWED and u[1] != "<module>"
                 and not u[0].startswith("app/tasks/enrich_manifest.py")]
    assert not offenders, (
        "These reach GeoClient outside the allowlist (ADR-584 D3): "
        f"{offenders}. A customer's address resolves through door_resolver. If this "
        "is the DSP's own place or the owner's, add it to ALLOWED with the reason.")


def test_every_allowed_entry_still_exists():
    """A stale entry would quietly cover a future caller of the same name."""
    seen = {u[:3] for u in _uses()}
    stale = sorted(ALLOWED - seen)
    assert not stale, f"ALLOWED names callers that no longer exist: {stale}"
