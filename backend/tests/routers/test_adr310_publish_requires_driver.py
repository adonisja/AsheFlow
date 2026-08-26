"""Publishing a truck with no driver (ADR-310).

`run_dispatch` warned "... will have no driver. Please assign manually." and
nothing downstream re-checked it. The two `role == "driver"` comparisons in
dispatch.py both live in dock-WRITING loops, so zero drivers was zero
iterations — a silent no-op that published a truck nobody was assigned to drive.

421 driverless truck-days reached `planned` on staging over two years; none ever
reached `active`. Latent, not realised — caught by discipline, not by code.
"""
import ast
import inspect

# Imported directly, with no skip guard. dispatch.py is gitignored from the
# public repo, but CI clones AsheFlow-private with a read-only deploy key and
# copies the proprietary routers in BEFORE pytest runs, so this import always
# resolves. A try/except ImportError here would convert a real breakage — a
# private branch that never synced, a drifted import — into a silent skip, and
# ci.yml calls that out by name: "skip-guarded tests silently skip".
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


# ── D4: a driver trainee is not a driver ─────────────────────────────────────

def test_only_role_driver_counts_not_trainees():
    """ADR-264 D6: a trainee and their supervising driver consume one truck and
    two drivers. Counting trainees as supply hides the shortfall exactly when it
    exists — so the guard must not widen to include them."""
    src = _code_only(D._trucks_missing_a_driver)
    assert "role == 'driver'" in src
    assert "driver_trainee" not in src, (
        "a driver trainee does not satisfy the requirement (ADR-310 D4)"
    )


# ── D1: planned stays usable ─────────────────────────────────────────────────

def test_the_guard_is_on_publish_not_on_assign():
    """421 driverless truck-days sat in `planned` — that is a board mid-build,
    not a corpus of mistakes. Refusing at assign time would fight the way the
    board is used (D1)."""
    for fn in (D.manual_assignment,):
        src = _code_only(fn)
        assert "_trucks_missing_a_driver" not in src, (
            f"{fn.__name__} must not gate on drivers — `planned` may hold a "
            f"driverless truck (ADR-310 D1)"
        )
    assert "_trucks_missing_a_driver" in _code_only(D.publish_dispatch)


# ── D2: both paths, each in its own scope ────────────────────────────────────

def test_bulk_publish_checks_every_truck():
    src = _code_only(D.publish_dispatch)
    assert "_trucks_missing_a_driver(db, caller.company_id, assignments)" in src


def test_per_truck_publish_checks_only_its_own_truck():
    """The hub usually leaves before the rest, so a per-truck publish is
    indifferent to other trucks' staffing — ADR-309 D3's rule, carried over."""
    src = _code_only(D.publish_hub)
    # ast.unparse normalises quotes to single — match on the normalised form.
    assert "am.role == 'driver'" in src
    assert "_trucks_missing_a_driver" not in src, (
        "publish_hub must not consult other trucks (ADR-310 D2)"
    )


# ── D3 / Dim 2: the refusal names its subject, and is correctly ordered ──────

def test_the_refusal_names_the_trucks():
    """A 409 that does not name its subject makes the dispatcher open six
    screens to find it (ADR-309 D1, ADR-300 D2b)."""
    src = _code_only(D.publish_dispatch)
    assert "no driver assigned" in src
    assert "', '.join(_no_driver)" in src

    hub = _code_only(D.publish_hub)
    assert "truck.name" in hub and "has no driver assigned" in hub


def test_already_published_is_reported_before_a_staffing_error():
    """Dimension 2: a re-publish must say "already published", not "no driver"."""
    src = _code_only(D.publish_dispatch)
    assert src.index("already been published") < src.index("_trucks_missing_a_driver")


def test_empty_crew_is_reported_before_missing_driver():
    """"No staff at all" and "staff but no driver" are different problems."""
    src = _code_only(D.publish_hub)
    assert (src.index("No staff assigned to hub yet")
            < src.index("am.role == 'driver'"))


# ── Dimension 1 ──────────────────────────────────────────────────────────────

def test_every_query_in_the_helper_is_company_scoped():
    src = _code_only(D._trucks_missing_a_driver)
    assert src.count("db.query(") == src.count("company_id ==")


# ── Dimension 5: counting the right unit ─────────────────────────────────────

def test_a_deterministic_message_order():
    """A truck missing both a driver and a dock must produce the SAME message
    every run, not one that depends on iteration order."""
    assert "sorted(" in _code_only(D._trucks_missing_a_driver)


# ── The calls actually resolve ───────────────────────────────────────────────

def test_internal_helper_calls_use_the_real_signatures():
    """A structural test does not CALL the endpoint, so a wrong keyword survives
    it — that is exactly how `_assignment(truck_assignment_id=...)` shipped and
    failed on the first real request (ADR-307)."""
    sig = inspect.signature(D._trucks_missing_a_driver)
    for fn in (D.publish_dispatch, D.publish_hub):
        tree = ast.parse(_code_only(fn))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "_trucks_missing_a_driver":
                continue
            kwargs = [k.arg for k in node.keywords if k.arg]
            for kw in kwargs:
                assert kw in sig.parameters, (
                    f"{fn.__name__} passes {kw}= which the helper does not declare"
                )
            assert len(node.args) + len(kwargs) <= len(sig.parameters)
            assert len(node.args) + len(kwargs) >= 3, (
                "db, company_id and assignments are all required"
            )
