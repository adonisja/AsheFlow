"""One implementation of "which truck am I on" (ADR-331).

Four mobile screens hand-rolled the same narrowing against /dispatch/{date}.
ADR-330 is the proof that duplication diverges: one of them read the DAY's
workflow_status instead of its own truck's status, closing the confirm window on
19 crew members' phones because a different truck had finalized.

Two screens are deliberately NOT adopted: FieldOps derives truckId from a
different endpoint, and DriverSurvey reads fields the payload has never had.
"""
import os
import re

import pytest

MOBILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mobile", "src")

ADOPTERS = [
    "screens/Home/TodayAssignmentScreen.tsx",
    "screens/Notifications/NotificationsScreen.tsx",
    "screens/Trainer/ReattemptScreen.tsx",
    "screens/Trainer/RouteSortScreen.tsx",
]


def _src(rel: str) -> str:
    path = os.path.abspath(os.path.join(MOBILE, rel))
    if not os.path.exists(path):
        pytest.fail(f"{rel} not found at {path}")
    return open(path).read()


# ── The helper exists and returns the per-truck answer ───────────────────────

def test_the_helper_returns_the_trucks_own_status_not_the_days():
    """THE reason the extraction exists: returning per-truck status by
    construction makes the ADR-329/330 class unexpressible through this path."""
    s = _src("hooks/useMyTruck.ts")
    assert "status: TruckStatus | null" in s
    assert "workflow_status" not in s.split("*/")[-1], (
        "the helper surfaces the day's status — a caller could reintroduce the bug"
    )


def test_the_helper_absorbs_both_assignment_id_spellings():
    """ReattemptScreen read `ta.id ?? ta.assignment_id` because it hit one of
    each. Four screens should not each have to know that."""
    s = _src("hooks/useMyTruck.ts")
    assert "ta?.id ?? ta?.assignment_id" in s


def test_the_helper_is_generic_over_the_crew_member_shape():
    """Three screens declare different CrewMember types and one keys on `id`
    rather than `employee_id`. A concrete type would force a type change on
    every caller, which is not behaviour-preserving."""
    s = _src("hooks/useMyTruck.ts")
    assert "<M extends CrewMemberLike>" in s
    assert "(m.employee_id ?? m.id)" in s


def _strip_comments(src: str) -> str:
    """Comments are prose and match their own subject.

    This test failed against correct code because the helper's docstring
    explains why it is NOT a hook — and says "useEffect" while doing so. The
    same false-positive shape that has now bitten a character-window assertion
    three times: grep the CODE, not the explanation of the code.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_the_helper_holds_no_state():
    """Named useX by convention; it is a pure function on purpose. A useX that
    is really a function invites a useEffect later and turns four synchronous
    derivations into four re-render sources."""
    code = _strip_comments(_src("hooks/useMyTruck.ts"))
    for react_api in ("useState", "useEffect", "useMemo", "useCallback"):
        assert react_api not in code, f"{react_api} makes this a real hook"
    assert "from 'react'" not in code and 'from "react"' not in code


# ── Adoption ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("screen", ADOPTERS)
def test_the_screen_uses_the_helper(screen):
    s = _src(screen)
    assert "useMyTruck" in s, f"{screen} does not use the shared helper"


@pytest.mark.parametrize("screen", ADOPTERS)
def test_no_screen_hand_rolls_the_lookup_any_more(screen):
    """The shape a regression takes: someone re-adds the local search."""
    s = _src(screen)
    assert "Object.entries(crews).find" not in s
    assert "Object.entries(assignedCrews).find" not in s


# ── Behaviour preservation (D4) ──────────────────────────────────────────────

def test_reattempt_still_filters_drivers_out_of_its_crew():
    """The helper replaces the LOOKUP, not the screen's logic."""
    assert "mine.crew.filter(m => m.role !== 'driver')" in _src(ADOPTERS[2])


def test_routesort_still_sets_the_viewer_and_reads_compliance():
    s = _src(ADOPTERS[3])
    assert "setViewerId(eid)" in s
    assert "crew-compliance" in s


def test_today_assignment_still_reads_the_arrival_stamp():
    s = _src(ADOPTERS[0])
    assert "ap_arrived_at" in s
    assert "assignment-members/" in s


def test_notifications_still_maps_none_to_planned():
    """ADR-274's rule must survive the refactor (ADR-330 D2)."""
    s = _src(ADOPTERS[1])
    assert "wf === 'none'" in s and "setDispatchPhase('planned')" in s


# ── The two deliberate non-adopters ──────────────────────────────────────────

def test_fieldops_is_deliberately_not_adopted():
    """It knows its truckId from /crew and only needs the assignment id.
    Forcing it through a crews search would add a lookup it does not need."""
    s = _src("screens/FieldOps/FieldOpsScreen.tsx")
    assert "useMyTruck" not in s
    assert "t.truck_id === truckId" in s


def test_driversurvey_header_now_reads_real_fields():
    """Was an INVERTED test asserting the bug still existed, so that whoever
    fixed it would trip this and find the ADR rather than re-deriving it.

    That is exactly what happened: ADR-332 D1 added `truck_name`, this test
    fired, and the header turned out to be only HALF fixable — the field
    existed but the code still flatMapped over a non-existent `ta.members`.
    Now it goes through useMyTruck, and the driver comes from the crew list
    (ADR-332 D3: a person does not belong on a row describing a vehicle).
    """
    code = _strip_comments(_src("screens/DriverSurvey/DriverSurveyScreen.tsx"))
    assert "ta.members" not in code, "still flatMapping a field that does not exist"
    assert "useMyTruck" in code
    assert "mine.truckName" in code
    assert "m.role === 'driver'" in code, "the driver must come from the crew list"
