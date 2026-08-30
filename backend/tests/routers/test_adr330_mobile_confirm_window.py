"""A crew member's confirm window is their own truck's (ADR-330).

Mobile half of the day-level-assumption sweep. NotificationsScreen derived
`dispatchPhase` from the DAY's workflow_status and used it to disable the
member's own confirm/decline buttons — so one truck finalizing closed the window
on every other truck's crew and relabelled them "No Response Recorded", which
reads as though THEY failed to reply.

Measured on staging 2026-08-29: 19 Eagle crew locked out because Falcon was
finalized. Third independent cause of one reported symptom (ADR-326 seeded no
rows, ADR-329 hid the dispatcher's control, this hid the crew's).
"""
import os
import re

import pytest

MOBILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mobile", "src")


def _src(rel: str) -> str:
    path = os.path.abspath(os.path.join(MOBILE, rel))
    if not os.path.exists(path):
        pytest.fail(f"{rel} not found at {path}")
    return open(path).read()


NOTIF = "screens/Notifications/NotificationsScreen.tsx"


def _phase_block() -> str:
    """The dispatchPhase-derivation block, bounded by its real end.

    A fixed character count silently truncates when the block grows — which
    happened here the moment the ADR-274 'none' branch was added, and made two
    assertions fail against code that was correct.
    """
    s = _src(NOTIF)
    i = s.index("if (dispatchResult.status === 'fulfilled')")
    j = s.index("}).finally(", i)
    return s[i:j]


# ── D1: the member's own truck ───────────────────────────────────────────────

def test_the_phase_is_not_derived_from_the_day_status():
    """THE finding."""
    block = _phase_block()
    assert "wf === 'finalized'" not in block, (
        "dispatchPhase still comes from the day's workflow_status — one "
        "finalized truck closes the window for every other truck's crew"
    )


def test_the_phase_is_derived_from_the_members_own_truck():
    """ADR-331 moved the narrowing into useMyTruck(), so this asserts the
    GUARANTEE (the phase comes from a per-truck resolution keyed on the viewer)
    rather than the literal lookup, which now lives in the helper."""
    block = _phase_block()
    assert "useMyTruck(data, userId)" in block, (
        "the member's truck is no longer resolved from the payload"
    )
    assert "mine.status === 'completed'" in block


def test_it_matches_the_pattern_the_rest_of_the_app_already_uses():
    """Was: does this screen match TodayAssignmentScreen's hand-rolled lookup.
    ADR-331 made them share one helper, so the assertion is now that both go
    through it — a stronger version of the same claim."""
    today = _src("screens/Home/TodayAssignmentScreen.tsx")
    assert "useMyTruck" in today, "the reference screen no longer uses the helper"
    assert "useMyTruck" in _phase_block()


# ── D2: the fallback direction ───────────────────────────────────────────────

def test_an_unresolvable_truck_leaves_the_window_open():
    """A wrong "closed" strips someone's ability to respond and then blames them
    for not responding. A wrong "open" shows a button that may 409 — visible and
    recoverable. Asymmetric failure modes: default to the recoverable one.

    Asserted on the fallback's OWN branch. A first version grepped a fixed
    window after `else {`, which also swallowed the 'none' branch below and
    started failing when that was added — the same character-window flaw the
    ADR-326 and ADR-328 mutation runs exposed.
    """
    block = _phase_block()
    tail = block[block.index("else {"):]
    # the non-'none' arm of the fallback
    m = re.search(r"else setDispatchPhase\('(\w+)'\);", tail)
    assert m, "the fallback's else-arm was not found"
    assert m.group(1) == "active", (
        f"the fallback sets '{m.group(1)}'; an unresolvable truck must leave the "
        "window OPEN (ADR-330 D2)"
    )


def test_a_day_with_no_dispatch_still_maps_to_planned():
    """ADR-274's rule survives: 'none' is a real answer ("nothing published"),
    not an unknown, and must not become 'active'. Two different unknowns, two
    different defaults — they must not share one."""
    block = _phase_block()
    tail = block[block.index("else {"):]
    assert "wf === 'none'" in tail
    assert "setDispatchPhase('planned')" in tail


# ── The hook recomputes ──────────────────────────────────────────────────────

def test_user_id_is_in_the_effect_dependencies():
    """userId is now read inside the effect. Without it in the deps, a modal
    opened before the id resolves keeps a phase computed from an empty userId."""
    s = _src(NOTIF)
    i = s.index("if (dispatchResult.status === 'fulfilled')")
    deps = s[i:i + 3000]
    m = re.search(r"\}, \[notif\?\.id, notif\?\.dispatch_date[^\]]*\]\);", deps)
    assert m, "the effect dependency array was not found"
    assert "userId" in m.group(0)


# ── What the gate actually controls ──────────────────────────────────────────

def test_the_phase_still_gates_the_action_buttons():
    """Guards the test above from going vacuous: if this wiring is renamed, the
    assertions about dispatchPhase stop meaning anything."""
    s = _src(NOTIF)
    assert "const isFinalized = dispatchPhase === 'completed';" in s
    assert "const windowClosed = isPastDate || isFinalized;" in s
    assert "!windowClosed" in s


# ── The other screens stay correct ───────────────────────────────────────────

@pytest.mark.parametrize("screen", [
    "screens/FieldOps/FieldOpsScreen.tsx",
    "screens/Trainer/ReattemptScreen.tsx",
    "screens/Trainer/RouteSortScreen.tsx",
])
def test_the_other_screens_narrow_to_their_own_truck(screen):
    """The sweep found these clean; pin them so a future edit cannot quietly
    adopt the day-level shortcut."""
    s = _src(screen)
    # ADR-331 — the adopted screens go through useMyTruck; FieldOps keeps its
    # own lookup because it gets truckId from a different endpoint.
    assert (
        "useMyTruck" in s
        or "truck_id === myTruckId" in s
        or "truck_id === truckId" in s
    ), f"{screen} no longer narrows the day payload to one truck"
