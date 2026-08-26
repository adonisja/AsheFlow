"""The operating zone is company configuration, not a sorting artifact (ADR-312).

`CompanyZone` lives in models/company.py next to CompanyConfig — the model was
always a company fact. The endpoints that define it sat in sort.py, which
main.py registers `_full_mode`, so RequireMode 404'd them in workforce mode.

Nothing about them is package-coupled. The gate is on the ROUTER, and zone
definition was swept along because of where the file sat: dsp-test — the
workforce tenant this exists for — could not define or read its own operating
area, and its one zone survived only because it was created while the company
was still full mode.
"""
import ast
import inspect

from app.routers import company_zones as CZ
from app.routers import sort as S
import app.main as M


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


ZONE_WRITES = (
    CZ.upsert_company_zone,
    CZ.upsert_company_zone_from_streets,
    CZ.upsert_company_zone_from_intersections,
    CZ.upsert_company_zone_from_corners,
)


# ── D1: reachable in BOTH modes ──────────────────────────────────────────────

def test_the_router_is_registered_for_both_modes():
    """THE regression this ADR fixes. `_full_mode` would 404 every one of these
    for a workforce tenant."""
    src = inspect.getsource(M)
    line = next(l for l in src.splitlines()
                if "company_zones.router" in l and "include_router" in l)
    assert "_configured" in line, "zone definition must not be mode-gated"
    assert "_full_mode" not in line
    assert "_workforce_mode" not in line, "full mode must keep working too"


def test_all_five_endpoints_moved():
    for fn in ZONE_WRITES + (CZ.get_company_zone,):
        assert fn.__module__ == "app.routers.company_zones"


def test_the_new_paths_are_registered():
    paths = {r.path for r in CZ.router.routes}
    assert paths == {
        "/company-zones",
        "/company-zones/from-streets",
        "/company-zones/from-intersections",
        "/company-zones/from-corners",
    }


# ── D5: not a permissions change ─────────────────────────────────────────────

def test_the_role_gates_are_unchanged():
    """"Workforce tenants can now define zones" sounds like a permissions change.
    It is not — it restores an ability never deliberately removed. Writes stay
    admin-only; the READ keeps its wider sort gate."""
    def gate(fn):
        for p in inspect.signature(fn).parameters.values():
            dep = getattr(p.default, "dependency", None)
            roles = getattr(dep, "allowed_roles", None)
            if roles:
                return set(roles)
        return set()

    for fn in ZONE_WRITES:
        assert gate(fn) == {"admin"}, f"{fn.__name__} must stay admin-only"
    assert gate(CZ.get_company_zone) == {"dispatch", "management", "admin"}, (
        "reading the operating zone is not an admin-only act (ADR-312 D5)"
    )


# ── D6: a superseded revision is deleted, not accumulated ────────────────────

def test_upserts_delete_the_previous_revision():
    """Deactivating grew the table by one dead row per edit, forever. Every
    reader filters is_active=True, so an inactive row is never read by
    anything."""
    for fn in ZONE_WRITES:
        src = _code_only(fn)
        assert ".delete(" in src, f"{fn.__name__} must delete the superseded row"
        assert '"is_active": False' not in src, (
            f"{fn.__name__} still deactivates instead of deleting (ADR-312 D6)"
        )


def test_the_delete_is_company_scoped_and_targets_only_the_live_root_zone():
    """Dimension 1: a delete that loses its scope removes another tenant's zone.
    This is the most dangerous line in the change."""
    for fn in ZONE_WRITES:
        src = _code_only(fn)
        seg = src[:src.index(".delete(")]
        assert "CompanyZone.company_id == caller.company_id" in seg, fn.__name__
        assert "CompanyZone.is_active.is_(True)" in seg, fn.__name__
        assert "CompanyZone.parent_zone_id.is_(None)" in seg, fn.__name__


def test_the_write_is_still_audited():
    """The audit is now the ONLY history, so it must survive the change."""
    for fn in ZONE_WRITES:
        assert "write_audit" in _code_only(fn)


# ── D3: the sort keeps its internal zone reads ───────────────────────────────

def test_sort_no_longer_defines_zones_but_may_still_read_them():
    src = inspect.getsource(S)
    assert "CompanyZone" in src, (
        "the sort still queries the zone to bound a day's work — that is sorting"
    )
    for name in ("_bbox_to_geojson", "_corners_to_geojson", "_geojson_to_bbox"):
        assert not hasattr(S, name), f"{name} should have moved to company_zones"


# ── D4: the old paths still answer ───────────────────────────────────────────

def test_the_deprecated_paths_delegate_rather_than_duplicate():
    """A client can outrun the backend that serves it, and a 404 on "save my
    operating zone" is a bad way to find out."""
    old = {r.path for r in S.router.routes if "company-zone" in r.path}
    # sort.router carries its own /sort prefix.
    assert old == {
        "/sort/company-zone", "/sort/company-zone/from-streets",
        "/sort/company-zone/from-intersections", "/sort/company-zone/from-corners",
    }
    # they must CALL the moved handlers, not carry their own copy of the logic
    for name in ("upsert_company_zone_deprecated",
                 "upsert_company_zone_from_streets_deprecated",
                 "upsert_company_zone_from_intersections_deprecated",
                 "upsert_company_zone_from_corners_deprecated",
                 "get_company_zone_deprecated"):
        src = _code_only(getattr(S, name))
        assert "_cz_" in src, f"{name} must delegate"
        assert "CompanyZone(" not in src, f"{name} must not re-implement the upsert"


def test_the_deprecated_routes_are_marked_deprecated():
    for r in S.router.routes:
        if "company-zone" in getattr(r, "path", ""):
            assert getattr(r, "deprecated", False), f"{r.path} should be deprecated=True"


# ── The names actually resolve ───────────────────────────────────────────────

def test_every_moved_symbol_exists():
    """`import app.main` passes even when a name inside a function body does not
    exist — it resolves at CALL time (ADR-301 lesson)."""
    for name in ("CornerPoint", "OperatingZoneOut", "OperatingZoneIn",
                 "OperatingZoneFromStreetsIn", "IntersectionIn",
                 "OperatingZoneFromIntersectionsIn", "OperatingZoneFromCornersIn",
                 "_bbox_to_geojson", "_corners_to_geojson",
                 "_geojson_to_corners", "_geojson_to_bbox"):
        assert hasattr(CZ, name), f"{name} did not survive the move"


def test_the_geojson_helpers_still_work():
    """Plain conversions — no proprietary geometry, which is why the move is safe."""
    poly = CZ._bbox_to_geojson(40.74, -74.01, 40.76, -73.99)
    assert poly["type"] == "Polygon"
    ring = poly["coordinates"][0]
    assert ring[0] == ring[-1], "the ring must be closed"
    assert len(ring) == 5, "4 corners plus the closing duplicate"
    corners = CZ._geojson_to_corners(poly)
    assert len(corners) == 4, "the closing duplicate is excluded"
    assert CZ._geojson_to_bbox(poly) == (40.74, -74.01, 40.76, -73.99)
