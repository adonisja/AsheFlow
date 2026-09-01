"""Per-truck controls read per-truck status (ADR-329).

Result of the deliberate sweep after four reactive fixes for one class. The
frontend gated per-MEMBER controls on `workflowStep`, which is the DAY's
furthest-along status — 'finalized' the moment any truck completes.

Measured on staging 2026-08-29: Falcon completed, five trucks active, so
workflow_status was 'finalized' and no crew member on any of the five could be
confirmed. That is a second, independent cause of the stuck-Eagle report:
ADR-326 seeded the missing rows, and this gate still hid the button.

These are source assertions because the dashboard has no test harness; they pin
the shape that the sweep verified against live data.
"""
import ast
import os
import re

import pytest

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                  "frontend", "src", "pages", "DispatchDashboard.tsx")


def _src() -> str:
    path = os.path.abspath(FE)
    if not os.path.exists(path):
        pytest.fail(f"DispatchDashboard.tsx not found at {path}")
    return open(path).read()


def _confirm_gate_line() -> str:
    for line in _src().split("\n"):
        if "conf !== 'confirmed'" in line and "isAdmin" in line:
            return line
    pytest.fail("the confirm-control gate was not found")


# ── D1: per-member controls ──────────────────────────────────────────────────

def test_the_confirm_control_reads_its_own_trucks_status():
    """THE finding. workflowStep is the day's furthest-along status."""
    line = _confirm_gate_line()
    assert "truckStatuses[truckId]" in line, (
        "the confirm control gates on a day-level value; one finalized truck "
        "hides it for every member of every truck still waiting (ADR-329 D1)"
    )
    assert "workflowStep" not in line


def test_the_transfer_control_is_also_per_truck():
    src = _src()
    assert "{(workflowStep === 'published' || workflowStep === 'finalized') && (" not in src, (
        "the transfer control still gates on the day's status"
    )


def test_the_truck_status_lookup_exists_and_is_derived_from_the_response():
    """No new endpoint: truck_assignments already carries per-truck status."""
    src = _src()
    assert "const truckStatuses = useMemo" in src
    block = src[src.index("const truckStatuses = useMemo"):]
    block = block[:block.index("}, [")]
    assert "truck_assignments" in block
    assert "a.status" in block


def test_the_lookup_is_declared_before_its_consumers():
    """A useMemo referenced before declaration is a runtime TDZ error that tsc
    does not always catch across a large component."""
    src = _src()
    decl = src.index("const truckStatuses = useMemo")
    for consumer in ("const confirmationGate = useMemo", "truckStatuses[truckId]"):
        assert decl < src.index(consumer), f"{consumer} precedes the declaration"


# ── D2: the finalize confirmation gate ───────────────────────────────────────

def test_the_confirmation_gate_is_not_multiplied_by_a_day_level_flag():
    """block/warn collapsed to false once any truck finalized, so the under-50%
    pre-flight warning stopped working for every truck still waiting."""
    src = _src()
    block = src[src.index("const confirmationGate = useMemo"):]
    block = block[:block.index("}, [")]
    assert "block: live &&" not in block
    assert "warn: live &&" not in block
    assert "block: below50.length > 0" in block


def test_the_gate_filters_trucks_by_their_own_status():
    src = _src()
    block = src[src.index("const confirmationGate = useMemo"):]
    block = block[:block.index("}, [")]
    assert "truckStatuses[t.truckId] === 'active'" in block, (
        "a finalized truck must drop out of the gate, and an active one must stay in"
    )


def test_the_gate_depends_on_the_status_lookup():
    """A stale useMemo would keep the old gating after a truck finalizes."""
    src = _src()
    i = src.index("const confirmationGate = useMemo")
    deps = src[src.index("}, [", i):src.index("]);", i)]
    assert "truckStatuses" in deps


# ── D3: day-level uses are deliberately kept ─────────────────────────────────

def test_workflow_step_survives_for_its_day_level_uses():
    """The rule is not "day-level status is wrong" but "a control's scope must
    match the status it reads." Deleting workflowStep would break the
    run-dispatch button and the day-level empty states."""
    src = _src()
    assert "workflowStep !== 'none'" in src or "workflowStep === 'none'" in src
    assert src.count("workflowStep") >= 3


# ── The regression this pairs with ───────────────────────────────────────────

def test_adr326_and_this_are_both_required():
    """Two independent defects produced one symptom. ADR-326 seeds the rows;
    this renders the control. Either alone leaves Eagle unconfirmable, which is
    why fixing one first looked like it had failed."""
    from app.routers import dispatch as D
    import inspect
    src = ast.unparse(ast.parse(inspect.getsource(D.publish_hub)))
    assert "overall_phase = assignment.status" in src, "ADR-326 D1 regressed"
