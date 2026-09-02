"""ADR-353 — the tridirectional bonus must be earnable under the live caps.

This is the regression that motivated the ADR. `perform_tridirectional_check`
requires all SIX directional favs among its trio. ADR-256 set `trainer→walker`
and `walker→trainer` to 0 for a defensible reason and did not notice this
consumer, so `count() == 6` became unreachable and a configurable 0.20 bonus
silently did nothing.

Nothing failed. No test broke. The feature just stopped existing.

These tests tie the two together: the trio the code checks must be a trio the
caps permit. Asserted by READING both from the source, not by restating them —
a restated copy is exactly what drifts.
"""
import ast
import inspect
import re

from app.routers import employee_relationships as ER
from app.services import calculate_weights as CW
from app.services.tridirectional import perform_tridirectional_check


def _fav_limits() -> dict:
    """Pull FAV_LIMITS out of the endpoint, where it is a function local."""
    src = inspect.getsource(ER.create_employee_relationship)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "FAV_LIMITS" for t in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError("FAV_LIMITS not found in create_employee_relationship")


def _trio_roles() -> list[str]:
    """The three roles the check is actually called with, read from the call site."""
    src = inspect.getsource(CW.calculate_weights)
    # e.g. captain_id = next((c["id"] ... if c["role"] == "captain"), None)
    roles = re.findall(r'c\["role"\]\s*==\s*"(\w+)"', src)
    # The walker is the candidate itself (employee_role == "walker"), not a lookup.
    return sorted(set(roles) | {"walker"})


def test_every_direction_in_the_trio_is_permitted():
    """The six favs the check requires must all be creatable.

    If any pair caps at 0 the bonus is dead code again — silently, because
    nothing raises: the count simply never reaches six.
    """
    limits = _fav_limits()
    trio = _trio_roles()
    assert len(trio) == 3, f"expected a trio, got {trio}"

    blocked = [
        f"{a}->{b} (cap {limits.get(a, {}).get(b, 0)})"
        for a in trio for b in trio
        if a != b and limits.get(a, {}).get(b, 0) == 0
    ]
    assert not blocked, (
        "the tridirectional bonus is UNREACHABLE — these directions cap at 0: "
        + ", ".join(blocked)
        + ". Either raise the cap or re-anchor the trio (ADR-353 D2)."
    )


def test_the_trio_is_driver_captain_walker():
    """Pin the ADR-353 D2 decision itself.

    Reachability alone is not enough: a trio of driver/captain/trainer would also
    pass the test above while rewarding a group that does not describe a crew.
    """
    assert _trio_roles() == ["captain", "driver", "walker"], (
        f"trio drifted to {_trio_roles()} — ADR-353 D2 anchors it on the three "
        "who share a truck: driver, captain, walker"
    )


def test_the_check_still_requires_all_six():
    """A weaker rule would be easier to earn and harder to reason about (D3)."""
    src = inspect.getsource(perform_tridirectional_check)
    assert "== 6" in src, "the six-direction requirement was weakened"
    pairs = re.findall(r"employee_id == (\w+),\s*EmployeeRelationship\.target_employee_id == (\w+)", src)
    assert len(pairs) == 6, f"expected 6 directional clauses, found {len(pairs)}"
    assert len(set(pairs)) == 6, "duplicate direction — one pair is checked twice"


def test_gaps_left_at_zero_are_the_documented_ones():
    """A cap of 0 is a decision about every consumer of that pair.

    Locking the intended gaps means a future removal has to change this test,
    which is where someone will read why the last one was a mistake.
    """
    limits = _fav_limits()
    expected_zero = {
        # One per truck, so the preference is meaningless (ADR-256, unchanged).
        ("driver", "driver"),
        ("captain", "captain"),
        # Low mutual impact; deliberately omitted from the ADR-353 mapping and
        # not needed by the trio.
        ("walker", "trainer"),
        # Two trainers favouring each other says nothing about how to build a
        # crew: neither leads the other, and each supervises their own trainee.
        # Confirmed as intended 2026-09-01. Noted explicitly because — unlike
        # driver→driver — it is NOT a one-per-truck consequence: trucks have
        # carried three trainers (staging, 2024-07-22 Viking).
        ("trainer", "trainer"),
    }
    actual_zero = {
        (a, b)
        for a in ("driver", "captain", "trainer", "walker")
        for b in ("driver", "captain", "trainer", "walker")
        if limits.get(a, {}).get(b, 0) == 0
    }
    assert actual_zero == expected_zero, (
        f"fav gaps changed: {sorted(actual_zero ^ expected_zero)} — "
        "check which consumers depend on the pair before changing a cap (ADR-353)"
    )


# ── The mobile mirror ────────────────────────────────────────────────────────

def test_the_mobile_mirror_matches_the_backend():
    """PreferencesScreen.tsx hand-copies FAV_LIMITS; a stale copy misleads users.

    The mobile table decides what the UI OFFERS, the backend decides what it
    ACCEPTS. Drift shows the user a choice that 409s on submit — or hides one
    they are entitled to.

    It had drifted badly: the copy predated the captain role, so it had no
    `captain` row at all (captains were offered nothing) and said
    trainer→trainer 1 where the backend said 0 (offered, then refused).
    """
    import os

    fe = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                      "mobile", "src", "screens", "Preferences", "PreferencesScreen.tsx")
    fe = os.path.abspath(fe)
    if not os.path.exists(fe):
        import pytest
        pytest.fail(f"PreferencesScreen.tsx not found at {fe}")

    src = open(fe).read()
    m = re.search(r"const FAV_LIMITS[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "FAV_LIMITS not found in PreferencesScreen.tsx"

    mobile: dict[str, dict[str, int]] = {}
    for role_line in re.finditer(r"(\w+)\s*:\s*\{([^}]*)\}", m.group(1)):
        role = role_line.group(1)
        mobile[role] = {
            k: int(v)
            for k, v in re.findall(r"(\w+)\s*:\s*(\d+)", role_line.group(2))
        }

    backend = _fav_limits()
    assert mobile == backend, (
        "mobile FAV_LIMITS has drifted from the backend.\n"
        f"  mobile:  {mobile}\n"
        f"  backend: {backend}\n"
        "The UI would offer a preference the server refuses, or hide one it allows."
    )
