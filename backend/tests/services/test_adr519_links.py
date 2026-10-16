"""ADR-519: every notification opens the thing it is about.

Walks the SOURCE for raise sites rather than iterating the registry: a
registry-walking test passes forever while new raise sites forget the id
(ADR-464's lesson).
"""
import ast
import pathlib
import re

import pytest

from app.services.notification_spec import LINK_KINDS, LINKS, RETIRED, SPEC, link_for
from app.schemas.notification import resolve_link

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
WEB_APP = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.tsx"

#: Raise sites whose `type=` is not a literal, keyed "relative/path.py:function",
#: with every type they can raise. A new dynamic site fails the walk until it is
#: listed here.
DYNAMIC = {
    "routers/anchor_points.py:_notify": {"anchor_point_arrived", "anchor_point_departed",
                                         "anchor_point_running_late", "anchor_point_submitted"},
    "routers/incidents.py:_notify_management": {"incident_critical", "incident_warning", "incident_info"},
    "routers/dispatch.py:manual_assignment": {"dispatch_assignment", "dispatch_assignment_info"},
    "routers/dispatch.py:swap_assignment": {"dispatch_assignment", "dispatch_assignment_info"},
    "routers/dispatch.py:publish_hub": {"dispatch_assignment", "dispatch_assignment_info"},
    "routers/shift_ops.py:review_rts_report": {"rts_approved", "rts_rejected"},
    "services/graduate_trainees.py:graduate_eligible_trainees": {"trainee_graduated"},
    "services/record_trainer_mark.py:_notify_management": {"underperforming_trainer", "exemplary_trainer"},
    "services/integration_alerts.py:alert_admins_integration_down": {
        "discord_integration_failed", "email_delivery_failed", "identity_revocation_failed"},
    "tasks/notice_sweep.py:_process_one": {"tenant_notice"},
}

#: Sites exempt from carrying an id, each with its reason.
EXEMPT = {
    "routers/notification_gallery.py:send_sample":
        "a gallery SAMPLE is about nothing; it opens its type's page (ADR-507)",
    "tasks/mfa_deadline_warnings.py:warn_before_mfa_deadline":
        "UNSCHEDULED since ADR-488 replaced it with a notice; raises undeclared types "
        "mfa_deadline_3d/1d. Tracked for deletion, not linked.",
}


def _sites():
    """(key, lineno, types, has_target_id) for every write_notification / fan_out call."""
    out = []
    for p in sorted(APP.rglob("*.py")):
        src = p.read_text()
        if "write_notification" not in src and "fan_out" not in src:
            continue
        tree = ast.parse(src)
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name not in ("write_notification", "fan_out"):
                continue
            enc = [fn for fn in funcs if fn.lineno <= node.lineno <= fn.end_lineno]
            fn = min(enc, key=lambda e: e.end_lineno - e.lineno).name if enc else "<module>"
            key = f"{p.relative_to(APP)}:{fn}"
            tkw = next((k.value for k in node.keywords if k.arg == "type"), None)
            types = {tkw.value} if isinstance(tkw, ast.Constant) else DYNAMIC.get(key)
            has = any(k.arg == "target_id" for k in node.keywords)
            out.append((key, node.lineno, types, has))
    return out


def test_the_walk_finds_the_raise_sites():
    assert len(_sites()) >= 80, "the source walk found too few sites; it would pass vacuously"


def test_every_declared_type_has_a_link():
    assert set(SPEC) == set(LINKS), sorted(set(SPEC) ^ set(LINKS))


def test_every_link_kind_is_known():
    assert {l.kind for l in LINKS.values() if l.kind} <= LINK_KINDS


def test_every_link_route_exists_in_the_web_router():
    routes = set(re.findall(r'path="([^"]+)"', WEB_APP.read_text()))
    templ = {re.sub(r":[A-Za-z]+", "{id}", r) for r in routes}
    missing = sorted({l.route for l in LINKS.values()} - routes - templ)
    missing += sorted({l.fallback for l in LINKS.values() if l.fallback} - routes)
    assert not missing, f"links to pages that do not exist (a 404 is a dead end): {missing}"


def test_every_dynamic_site_is_listed():
    unknown = sorted({k for k, _l, t, _h in _sites() if t is None and k not in EXEMPT})
    assert not unknown, f"raise sites with a computed type: list their types in DYNAMIC: {unknown}"


def test_dynamic_types_are_declared():
    for key, types in DYNAMIC.items():
        assert types <= set(SPEC), (key, types - set(SPEC))


def test_every_raise_site_of_a_linked_type_passes_its_id():
    missing = []
    for key, line, types, has in _sites():
        if key in EXEMPT or not types:
            continue
        needs = {t for t in types if link_for(t).kind}
        if needs and not has:
            missing.append(f"{key}:{line} {sorted(needs)}")
    assert not missing, (
        f"{len(missing)} raise site(s) send a type that opens a specific item but pass no "
        f"target_id, so the notification would open only the page:\n  " + "\n  ".join(missing))


class TestResolveLink:
    class Row:
        def __init__(self, target_id=None, dispatch_date=None):
            self.target_id, self.dispatch_date = target_id, dispatch_date

    def test_fills_the_id_into_a_templated_route(self):
        assert resolve_link("driver_help_requested", self.Row("abc"))["route"] == "/help-requests/abc"

    def test_a_row_without_an_id_opens_the_fallback_not_a_broken_path(self):
        out = resolve_link("driver_help_requested", self.Row())
        assert out["route"] == "/dispatch" and out["id"] is None

    def test_carries_kind_id_and_date(self):
        from datetime import date
        out = resolve_link("anchor_point_running_late", self.Row("t1", date(2026, 10, 15)))
        assert out == {"route": "/anchor-points", "kind": "truck", "id": "t1", "date": "2026-10-15"}

    def test_a_page_level_type_has_no_id_even_if_one_is_stored(self):
        assert resolve_link("zone_sort_complete", self.Row("x"))["id"] is None

    def test_a_retired_or_unknown_type_opens_the_inbox(self):
        assert resolve_link(next(iter(RETIRED)))["route"] == "/notifications"
        assert resolve_link("no_such_type")["route"] == "/notifications"


MOBILE_ROUTES = pathlib.Path(__file__).resolve().parents[3] / "mobile" / "src" / "navigation" / "actionRoutes.ts"


def _code(path):
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.mark.parametrize("route", sorted({l.route for l in LINKS.values() if "{id}" not in l.route}))
def test_every_link_route_is_mapped_or_declared_unmapped_on_mobile(route):
    """A link the phone cannot resolve must be a decision (DELIBERATELY_UNMAPPED,
    falling back to the inbox), not an omission. Templated routes are resolved
    by kind (a help request opens a sheet), so they are not in the map."""
    assert f"'{route}'" in _code(MOBILE_ROUTES), (
        f"{route} (a notification link) is neither mapped nor DELIBERATELY_UNMAPPED in actionRoutes.ts")
