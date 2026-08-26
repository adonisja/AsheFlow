"""A dispatch DM with no dock line sends a driver to a warehouse with no
instructions (ADR-309).

publish_dispatch called _resolve_dock_zone and carried on when it returned
None. The consequence was already written down, in a comment two lines above
the call: "must be persisted here or the driver's DM silently omits the dock
line". The failure was anticipated and not guarded.

Measured on staging while writing the ADR: 7 of 7 trucks had no dock_zone.
"""
import ast
import inspect

# No skip guard (ADR-311): CI copies the proprietary routers in from
# AsheFlow-private before pytest runs, so a failed import is a real failure.
from app.routers import dispatch as D


def _code_only(obj) -> str:
    """Source with docstrings stripped — grep matches its own prose otherwise."""
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1: the bulk path refuses, and names the trucks ──────────────────────────

def test_bulk_publish_refuses_when_any_truck_has_no_dock():
    src = _code_only(D.publish_dispatch)
    assert "_dockless" in src
    assert "have no dock assigned" in src


def test_the_refusal_names_the_trucks():
    """"Some trucks are missing a dock" makes a dispatcher open six screens to
    find which (ADR-300 D2b)."""
    src = _code_only(D.publish_dispatch)
    assert "', '.join(sorted(_dockless))" in src


# ── D1/D5: the guard runs BEFORE anything is sent ────────────────────────────

def test_the_dock_is_settled_before_any_notification_goes_out():
    """THE defect. The resolve loop used to run after the DMs, the in-app
    notifications and the status flip — which is why a dockless truck-day could
    be published at all. Refusing has to still be free at that point."""
    src = _code_only(D.publish_dispatch)
    assert src.index("_dockless") < src.index("Notification("), (
        "the dock guard must precede notification seeding (ADR-309 D1)"
    )


def test_only_one_resolve_loop_survives():
    """The late loop was removed, not left in place — a second pass would
    re-resolve bays already settled and re-run the write-back."""
    src = _code_only(D.publish_dispatch)
    assert src.count("_resolve_dock_zone") == 1


# ── D5: every truck resolved before any refusal ──────────────────────────────

def test_resolution_is_not_abandoned_on_the_first_miss():
    """_resolve_dock_zone WRITES BACK an inherited bay (ADR-274 D17). Refusing
    on the first miss would leave later trucks' inheritance unrecorded and make
    the outcome depend on iteration order."""
    tree = ast.parse(_code_only(D.publish_dispatch))
    loops = [n for n in ast.walk(tree)
             if isinstance(n, ast.For)
             and any("_dockless" in ast.dump(c) for c in ast.walk(n))]
    assert loops, "expected a loop collecting dockless trucks"
    for loop in loops:
        for node in ast.walk(loop):
            assert not isinstance(node, ast.Raise), (
                "the resolve loop must COLLECT failures, not raise on the first "
                "miss — an early raise leaves later trucks' inherited bays "
                "unrecorded and makes the outcome order-dependent (ADR-309 D5)"
            )
    assert "if _dockless:" in _code_only(D.publish_dispatch)


def test_bays_that_did_resolve_are_persisted_even_on_a_refused_request():
    """D5: the write-back must survive a request that then fails."""
    src = _code_only(D.publish_dispatch)
    head = src[:src.index("have no dock assigned")]
    assert "db.commit()" in head[head.index("if _dockless:"):], (
        "commit the resolved bays before raising (ADR-309 D5)"
    )


# ── D3: the per-truck path is NOT gated on other trucks ──────────────────────

def test_per_truck_publish_checks_only_its_own_truck():
    """The correction the operator made to this ADR's first draft.

    Publishing ONE truck whose dock IS set is routine — the hub typically leaves
    before the other trucks. Blocking that because an unrelated truck has no bay
    would break normal operation to prevent a mistake it cannot make.
    """
    src = _code_only(D.publish_hub)
    assert "has no dock assigned" in src
    assert "_dockless" not in src, (
        "publish_hub must not consult other trucks' docks (ADR-309 D3)"
    )
    assert "_resolve_dock_zone(db, caller.company_id, assignment)" in src


def test_the_per_truck_dock_guard_precedes_its_notifications():
    src = _code_only(D.publish_hub)
    assert src.index("has no dock assigned") < src.index("Notification(")


# ── Cross-ADR ordering (Dimension 2) ─────────────────────────────────────────

def test_staffing_is_reported_before_a_missing_bay():
    """A truck missing BOTH a driver and a dock must produce the same message
    every run. Driver first: a bay for a truck nobody drives is moot."""
    for fn in (D.publish_dispatch, D.publish_hub):
        src = _code_only(fn)
        assert src.index("no driver") < src.index("no dock assigned"), (
            f"{fn.__name__}: ADR-310's driver guard must precede ADR-309's dock guard"
        )


def test_already_published_is_still_reported_first():
    src = _code_only(D.publish_dispatch)
    assert src.index("already been published") < src.index("_dockless")


# ── Dimension 1 ──────────────────────────────────────────────────────────────

def test_the_truck_name_lookup_is_company_scoped():
    """A bare Truck.id lookup would resolve another tenant's truck if an id ever
    leaked into this path."""
    src = _code_only(D.publish_dispatch)
    seg = src[src.index("_dock_names = {"):src.index("_dockless: list[str] = []")]
    assert "Truck.company_id == caller.company_id" in seg


def test_the_guard_does_not_depend_on_state_built_after_it():
    """truck_map is assembled further down; referencing it here is a NameError
    on the failure path only — invisible to a structural test that never calls
    the endpoint (the ADR-307 lesson)."""
    import builtins
    import app.routers.dispatch as _mod

    fn = ast.parse(_code_only(D.publish_dispatch)).body[0]
    # EVERY statement of the guard, not just the first mentioning _dockless.
    # Scoping to that first node made this test inspect the annotation
    # `_dockless: list[str] = []` and miss the loop underneath it — where the
    # real NameError lived.
    idx = next(i for i, n in enumerate(fn.body) if "_dockless" in ast.dump(n))
    end = next((i for i, n in enumerate(fn.body)
                if i > idx and "_dockless" not in ast.dump(n)
                and not isinstance(n, (ast.For, ast.If))), len(fn.body))
    guard_nodes = fn.body[idx:end]
    guard = ast.Module(body=guard_nodes, type_ignores=[])

    # Everything bound before the guard: parameters, assignments, imports.
    bound = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    for node in fn.body[:idx]:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                bound.add(sub.id)
            elif isinstance(sub, ast.alias):
                bound.add(sub.asname or sub.name.split(".")[0])

    # Names the guard block itself binds (e.g. _dockless, the loop variable).
    for sub in ast.walk(guard):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            bound.add(sub.id)
        elif isinstance(sub, ast.comprehension):
            for t in ast.walk(sub.target):
                if isinstance(t, ast.Name):
                    bound.add(t.id)

    for sub in ast.walk(guard):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            assert sub.id in bound or hasattr(_mod, sub.id) or hasattr(builtins, sub.id), (
                f"the dock guard reads `{sub.id}`, which is not bound before it — "
                f"a NameError on the failure path only, invisible to a structural "
                f"test that never calls the endpoint (ADR-307 lesson)"
            )
