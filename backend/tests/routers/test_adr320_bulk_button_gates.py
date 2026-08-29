"""One published truck must not strand the rest of the day (ADR-320).

A dispatcher published Atlas alone and the bulk "Publish Initial Confirmations
to Discord" button went dead for the other five. Measured on staging:

    Atlas    active     <- the one published
    Eagle    planned
    Falcon   planned
    Morgan   planned
    Titan    planned
    Viking   planned

    -> workflow_status = 'published'   (the furthest-along status wins)
    -> button gated on workflowStep === 'dispatched'  -> disabled

Five trucks whose crews were never DMed became unreachable through the button
meant to reach them.
"""
import inspect
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DASH = BACKEND.parent / "frontend" / "src" / "pages" / "DispatchDashboard.tsx"


def _src() -> str:
    return DASH.read_text(encoding="utf-8")


# ── The server was always right; the client refused to call it ───────────────

def test_the_server_already_skips_an_already_published_truck():
    """publish_dispatch filters to planned trucks, so a mixed day publishes the
    remainder and sends no second DM. This is why the fix is client-side."""
    from app.routers import dispatch as D
    src = inspect.getsource(D.publish_dispatch)
    assert 'a.status == "planned"' in src
    assert 'already_published' in src


def test_workflow_status_still_collapses_the_day_on_purpose():
    """`none` and `finalized` remain genuine day-level facts, and Run Dispatch
    gates on `none`. The defect was USING a summary where a count is needed —
    not the summary existing (ADR-320 D2)."""
    from app.routers import dispatch as D
    src = inspect.getsource(D)
    assert 'workflow_status = "published"' in src
    assert '"active" in operational_statuses' in src


# ── D1: the bulk buttons read counts ─────────────────────────────────────────

def test_the_bulk_publish_gates_on_trucks_still_planned():
    src = _src()
    assert "phaseCounts.planned === 0" in src
    # the collapsed status must no longer gate this button
    assert "workflowStep !== 'dispatched'" not in src, (
        "the bulk publish must not gate on the day's furthest-along status"
    )


def test_the_finalize_gates_on_trucks_still_active():
    """Mirror-image failure: the first truck to complete made the day
    'finalized', killing the button for every truck still active."""
    src = _src()
    assert "phaseCounts.active === 0" in src
    assert "workflowStep !== 'published'" not in src


def test_run_dispatch_still_gates_on_the_day_level_status():
    """It is a genuine day-level question and is deliberately untouched."""
    src = _src()
    assert "workflowStep !== 'none'" in src


# ── D1 / Dim 5: hubs are excluded the same way ───────────────────────────────

def test_the_counts_exclude_hubs():
    """`workflow_status` excludes hubs (ADR-274/286). If the counts did not, a
    hub-only day would re-enable a button it should not."""
    src = _src()
    block = src[src.index("const phaseCounts"):src.index("const phaseCounts") + 700]
    assert "!a.is_hub" in block


def test_the_counts_come_from_per_truck_status():
    src = _src()
    block = src[src.index("const phaseCounts"):src.index("const phaseCounts") + 700]
    assert "truck_assignments" in block
    assert "'planned'" in block and "'active'" in block


# ── D3: a disabled button says why ───────────────────────────────────────────

def test_the_label_says_what_pressing_it_will_do():
    """With a mixed day the plain label overstates — an already-published truck
    is skipped. A disabled button with no explanation is what made this look
    broken rather than finished."""
    src = _src()
    assert "All trucks published" in src
    assert "Publish Remaining ${phaseCounts.planned}" in src


def test_the_all_published_state_is_explained_in_the_tooltip():
    src = _src()
    assert "Every truck has already been published" in src


# ── D4: the dock gate keeps its own scope ────────────────────────────────────

def test_the_dock_gate_still_blocks_the_bulk_publish():
    """ADR-309 D1 asks "is the whole day ready?", which is a different question
    from "which trucks remain?". Both now sit on the same button."""
    src = _src()
    i = src.index("phaseCounts.planned === 0 || dockGate.block")
    assert i > 0, "the dock gate must still be ANDed into the publish button"
