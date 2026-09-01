"""An error nobody can see is a silent failure (ADR-333).

The operator reported hub publish "failing silently" with a 409. The message
existed, was correct, and WAS rendered — in a banner at the top of a page whose
per-truck controls sit ~540 lines further down. Displayed and seen are the same
thing to a user, and only the second one counts.

Second finding from the same screenshots: a 400 rendered a raw employee UUID.
"""
import ast
import inspect
import os
import re

import pytest

from app.routers import dispatch as D

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                  "frontend", "src", "pages", "DispatchDashboard.tsx")


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


def _strip_comments(src: str) -> str:
    """Comments describe their own subject and match greps aimed at code."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _fe() -> str:
    p = os.path.abspath(FE)
    if not os.path.exists(p):
        pytest.fail(f"DispatchDashboard.tsx not found at {p}")
    return open(p).read()


# ── D1: the banner comes to the operator ─────────────────────────────────────

def test_the_error_banner_scrolls_itself_into_view():
    """THE finding. A correct message painted off-screen reads as silence.

    Asserted on the CALL being reachable, not merely present. A first version
    checked `"scrollIntoView" in code` and survived a mutation prefixing it with
    `void 0 &&` — the entire fix disabled, tests green. Presence is not
    reachability.
    """
    # ADR-339 D4 moved the implementation into the shared `useErrorBanner`
    # hook, so this page no longer contains scrollIntoView. The GUARANTEE is
    # unchanged and is asserted where it now lives; here we assert the page
    # still goes through it rather than having lost the behaviour.
    code = _strip_comments(_fe())
    assert "useErrorBanner(error)" in code, (
        "the page no longer wires the error banner to the scroll behaviour"
    )

    hook = _strip_comments(open(os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "frontend", "src", "hooks", "useErrorBanner.ts"))).read())
    i = hook.index("scrollIntoView")
    line_start = hook.rindex("\n", 0, i) + 1
    stmt = hook[line_start:i]
    assert stmt.strip() in ("ref.current?.", "ref.current."), (
        f"scrollIntoView is not a reachable statement on the ref (got {stmt.strip()!r})"
    )


def test_the_scroll_is_driven_by_the_error_state_not_the_call_sites():
    """Done once as an effect on `error`, so the 13th setError caller gets it
    free rather than being forgotten."""
    # ADR-339 D4 — now asserted in the hook, which is where the effect lives.
    hook = _strip_comments(open(os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "frontend", "src", "hooks", "useErrorBanner.ts"))).read())
    assert "useEffect" in hook, "the scroll is not an effect on the error state"
    assert "}, [error]);" in hook


def test_the_banner_carries_the_ref():
    """Without the ref on the rendered node the effect scrolls nothing."""
    code = _strip_comments(_fe())
    assert "ref={errorRef}" in code
    i = code.index("ref={errorRef}")
    assert "border-danger" in code[i:i + 200], "the ref is not on the error banner"


def test_reduced_motion_is_respected():
    """CLAUDE.md: an animation that ignores prefers-reduced-motion is a bug."""
    # ADR-339 D4 — lives in the hook now.
    hook = _strip_comments(open(os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "frontend", "src", "hooks", "useErrorBanner.ts"))).read())
    assert "prefers-reduced-motion" in hook
    assert "reduced ? 'auto' : 'smooth'" in hook


# ── D2: which truck failed ───────────────────────────────────────────────────

def test_a_failed_per_truck_action_marks_its_own_truck():
    """Reading the banner means scrolling away from the card; on a six-truck day
    "which one?" is then ambiguous."""
    code = _strip_comments(_fe())
    assert "truckActionError" in code
    assert "truckActionError[truckId]" in code, "the marker is never rendered"


def test_the_marker_is_cleared_on_a_fresh_attempt():
    """A stale marker on a truck that now publishes fine is its own lie."""
    code = _strip_comments(_fe())
    assert code.count("delete n[truckId]") >= 2, (
        "publish and finalize must each clear the truck's marker before retrying"
    )


def test_both_per_truck_actions_set_a_marker():
    code = _strip_comments(_fe())
    assert "Publish failed" in code
    assert "Post final crew failed" in code


# ── D3: the 400 names the employee ───────────────────────────────────────────

def test_the_reassignment_rejection_names_the_employee():
    """A UUID is unreadable to the operator and useless without DB access —
    the same rule as ADR-309 D1 and ADR-328 D5."""
    src = _code_only(D.swap_assignment)
    assert "Employee {assignment_in.employee_id} is already assigned" not in src
    assert "is already assigned to this truck" in src
    assert "_name or 'That employee'" in src


def test_the_name_lookup_is_company_scoped():
    """Dim 1 — an unscoped lookup could name another tenant's employee."""
    tree = ast.parse(_code_only(D.swap_assignment))
    assign = next(
        (ast.unparse(n) for n in ast.walk(tree)
         if isinstance(n, ast.Assign)
         and any(getattr(t, "id", None) == "_name" for t in n.targets)),
        None,
    )
    assert assign is not None, "the name lookup was not found"
    assert "Employee.company_id == caller.company_id" in assign


def test_the_fallback_is_a_phrase_not_the_uuid():
    """A UUID is never the better half of that fallback.

    Asserted on the DETAIL STRING, not a character window before it. A first
    version looked back 200 chars and caught `employee_id` from the name LOOKUP
    on the line above — which is where the id legitimately belongs. Sixth
    appearance of the character-window false positive this week.
    """
    tree = ast.parse(_code_only(D.swap_assignment))
    detail = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "detail" and "is already assigned to this truck" in ast.unparse(kw.value):
                detail = ast.unparse(kw.value)
    assert detail is not None, "the reassignment detail string was not found"
    assert "employee_id" not in detail, (
        f"the UUID is interpolated into the message: {detail}"
    )
    assert "_name" in detail


# ── D4: the guards themselves are unchanged ──────────────────────────────────

def test_the_publish_guards_still_refuse():
    """The complaint was visibility of the refusal, not the refusal. Weakening
    a guard to make its message easier to notice would solve the wrong problem."""
    src = _code_only(D.publish_hub)
    assert "has no driver assigned" in src
    assert "has no dock assigned" in src
    assert src.count("HTTP_409_CONFLICT") >= 3
