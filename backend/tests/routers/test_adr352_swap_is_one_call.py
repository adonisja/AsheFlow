"""ADR-352 — a driver/captain swap is ONE call, not two.

`PATCH /dispatch/assign` already performs the whole exchange for a one-per-truck
role (ADR-321): it parks the member holding the destination slot as `walker`,
moves the incoming member in, then moves the parked one to the vacated source —
one transaction, no constraint violation.

The frontend sent a SECOND call for B anyway. Call 1 had already moved B, so
call 2 asked to move B where B now was and the backend correctly refused it as a
no-op: "… is already assigned to this truck with this role. Reassignment
rejected." The swap had actually succeeded; the operator saw a red banner on a
completed change and resorted to delete-then-re-add.

Reproduced on staging against the real indexes before fixing: the ADR-321
sequence swapped Brianna Tate (Atlas) and Darius Webb (Eagle) cleanly in one
transaction.
"""
import ast
import inspect
import os
import re

import pytest

from app.routers import dispatch as D

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                  "frontend", "src", "pages", "DispatchDashboard.tsx")


def _strip_comments(src: str) -> str:
    """Comments explain this very bug and match greps aimed at code."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _fe() -> str:
    p = os.path.abspath(FE)
    if not os.path.exists(p):
        pytest.fail(f"DispatchDashboard.tsx not found at {p}")
    return open(p).read()


def _swap_two_body() -> str:
    """The body of swapTwo, comments removed."""
    code = _strip_comments(_fe())
    i = code.find("const swapTwo")
    assert i != -1, "swapTwo not found — was it renamed?"
    # Bounded by the next top-level `const <name> =` declaration.
    m = re.search(r"\n  const \w+ = ", code[i + 10:])
    return code[i: i + 10 + (m.start() if m else 4000)]


def test_swap_does_not_unconditionally_send_two_calls():
    """The regression itself: an unguarded second PATCH re-sends B.

    Two calls are also two transactions, so an interruption between them strands
    a crew member on the wrong truck — worse than the error it caused.
    """
    body = _swap_two_body()
    calls = body.count("axiosClient.patch")
    assert calls <= 2, f"swapTwo makes {calls} PATCH calls; expected at most 2"
    if calls == 2:
        # A second call is legitimate ONLY for roles the backend does not
        # displace. It must be conditional, never unconditional.
        assert re.search(r"if\s*\(.*ONE_PER_TRUCK", body), (
            "the second PATCH must be gated on the role NOT being one-per-truck; "
            "an unconditional second call re-sends B and trips the no-op guard"
        )


def test_the_frontend_role_set_matches_the_backend():
    """A drifted copy silently half-completes a swap.

    If the frontend thinks `driver` is not one-per-truck it sends the redundant
    call again; if it thinks `walker` IS, it skips a call that was needed and B
    never moves.
    """
    body = _swap_two_body()
    m = re.search(r"ONE_PER_TRUCK\s*=\s*new Set\(\[([^\]]*)\]\)", body) \
        or re.search(r"ONE_PER_TRUCK\s*=\s*new Set\(\[([^\]]*)\]\)", _strip_comments(_fe()))
    assert m, "ONE_PER_TRUCK set not found in the frontend"
    fe_roles = {s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()}
    be_roles = set(D._ONE_PER_TRUCK_ROLES)
    assert fe_roles == be_roles, (
        f"frontend {sorted(fe_roles)} != backend {sorted(be_roles)} — "
        "a swap will half-complete on the roles they disagree about"
    )


def test_the_backend_still_displaces_the_occupant():
    """The single call only works because the backend does the exchange.

    Asserted on the parking sequence, not merely on a symbol existing: ADR-321's
    whole point is that a bare partial unique index is not deferrable, so the
    displaced member must hop to a role outside every index's WHERE clause.
    """
    src = ast.unparse(ast.parse(inspect.getsource(D.swap_assignment)))
    assert "_ONE_PER_TRUCK_ROLES" in src, "the displacement gate is gone"
    assert "_PARKED_ROLE" in src, "the park-by-role step is gone"
    assert D._PARKED_ROLE not in D._ONE_PER_TRUCK_ROLES, (
        "the parked role must sit outside every partial unique index"
    )


def test_the_trainer_path_is_untouched():
    """A trainer swap still sends TWO calls, exactly as before this fix.

    `trainer` is not one-per-truck, so the backend does not displace them: call 1
    moves the trainer (and, in the same transaction, their paired trainees —
    ADR-210 step 4b), call 2 moves the counterpart. Collapsing that to one call
    would move the trainer and silently leave the other member behind.

    Asserted on the GATE's membership rather than on the call count, because the
    count alone cannot distinguish "correctly two" from "unconditionally two".
    """
    body = _swap_two_body()
    m = re.search(r"ONE_PER_TRUCK\s*=\s*new Set\(\[([^\]]*)\]\)", body) \
        or re.search(r"ONE_PER_TRUCK\s*=\s*new Set\(\[([^\]]*)\]\)", _strip_comments(_fe()))
    assert m, "ONE_PER_TRUCK set not found"
    roles = {s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()}
    for role in ("trainer", "trainee", "walker", "driver_trainee"):
        assert role not in roles, (
            f"{role!r} must NOT be treated as one-per-truck — the backend does not "
            f"displace it, so skipping the second call would half-complete the swap"
        )


def test_paired_trainees_still_travel_with_their_trainer():
    """ADR-210 step 4b — the behaviour the fix must not disturb.

    This lives entirely in the backend and the fix touched no backend file; the
    test pins it so a later 'simplification' of swap_assignment cannot drop it
    unnoticed.
    """
    src = ast.unparse(ast.parse(inspect.getsource(D.swap_assignment)))
    assert "paired_trainer_id" in src, "the trainer->trainee pairing logic is gone"
    assert "ROLE_TRAINER" in src, "the trainer branch is gone"
