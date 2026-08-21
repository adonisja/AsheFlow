"""Which ADP/Flex disagreements become findings (ADR-233 Phase 4).

The rule is "does Flex hold data that resolves it?", not "does ADP have a
problem?". ADP sees its own gaps and reports them natively; only AsheFlow sees
both sides, so only a disagreement Flex can fix is a finding here.

Every case below either produces exactly one finding_type or produces nothing.
The nothing-cases matter as much as the findings: a false positive becomes a
proposed payroll correction sent to an employee for sign-off.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.tasks.adp_mismatch_detect import _classify, MISMATCH_TOLERANCE
from app.tasks.adp_sync import _primary_work_assignment_id


WORK_DATE = date(2026, 7, 24)


def _at(hour, minute=0):
    return datetime(2026, 7, 24, hour, minute, tzinfo=timezone.utc)


def _flex(start=_at(12), end=_at(12, 30)):
    return SimpleNamespace(break_start_at=start, break_end_at=end)


def _timecard(is_working_day=True):
    return SimpleNamespace(work_date=WORK_DATE, is_working_day=is_working_day, id="tc-1")


def _brk(start, end, type_code=None, entry_id="E1"):
    return SimpleNamespace(
        adp_entry_id=entry_id, start_at=start, end_at=end,
        break_type_code=type_code, break_item_id="1",
    )


def _type_of(result):
    return result[0] if result else None


# ── entry_missing_in_adp ─────────────────────────────────────────────────────

def test_no_adp_entries_on_a_flex_working_day():
    got = _classify(_timecard(is_working_day=False), [], _flex())
    assert _type_of(got) == "entry_missing_in_adp"
    assert got[1] is None      # no entryID to correct against


# ── break_missing_in_adp ─────────────────────────────────────────────────────

def test_entries_exist_but_no_breaks():
    got = _classify(_timecard(), [], _flex())
    assert _type_of(got) == "break_missing_in_adp"


def test_breaks_exist_but_none_measurable():
    """A break ADP reports without an end time cannot be compared."""
    got = _classify(_timecard(), [_brk(_at(12), None, "meal")], _flex())
    assert _type_of(got) == "break_missing_in_adp"


# ── break_short_in_adp ───────────────────────────────────────────────────────

def test_adp_break_short_while_flex_is_compliant():
    """ADP under-recorded: Flex holds the correct 30-minute window."""
    got = _classify(
        _timecard(),
        [_brk(_at(12), _at(12, 20), "meal")],       # 20 min
        _flex(_at(12), _at(12, 30)),                # 30 min
    )
    assert _type_of(got) == "break_short_in_adp"
    assert got[1] == "E1"                            # entryID carried for the write


def test_both_systems_agree_the_break_was_short_is_not_a_finding():
    """No disagreement, nothing for Flex to supply, and ADP reports the
    meal-break violation natively. Surfacing it would duplicate ADP."""
    got = _classify(
        _timecard(),
        [_brk(_at(12), _at(12, 20), "meal")],       # 20 min
        _flex(_at(12), _at(12, 22)),                # 22 min — also short
    )
    assert got is None


# ── break_time_mismatch ──────────────────────────────────────────────────────

def test_windows_differ_beyond_tolerance():
    got = _classify(
        _timecard(),
        [_brk(_at(12), _at(12, 30), "meal")],
        _flex(_at(13), _at(13, 30)),                # an hour later
    )
    assert _type_of(got) == "break_time_mismatch"
    assert got[2] == _at(12) and got[3] == _at(12, 30)   # ADP's window, for the description


def test_agreement_within_tolerance_is_not_a_finding():
    """Clock drift between two systems is not a disagreement."""
    got = _classify(
        _timecard(),
        [_brk(_at(12, 2), _at(12, 33), "meal")],
        _flex(_at(12), _at(12, 30)),                 # 2 and 3 minutes off
    )
    assert got is None


def test_exactly_at_tolerance_is_not_a_finding():
    """The gate is >5 minutes, not >=."""
    flex = _flex(_at(12), _at(12, 30))
    shifted = _at(12) + MISMATCH_TOLERANCE
    got = _classify(_timecard(), [_brk(shifted, _at(12, 35), "meal")], flex)
    assert got is None


def test_start_alone_out_of_tolerance_is_enough():
    got = _classify(
        _timecard(),
        [_brk(_at(11, 40), _at(12, 30), "meal")],    # start 20 min early
        _flex(_at(12), _at(12, 30)),                 # end matches
    )
    assert _type_of(got) == "break_time_mismatch"


# ── selection feeds classification ───────────────────────────────────────────

def test_short_meal_falls_through_to_a_longer_untyped_break():
    """Selection prefers a meal only once it clears 30 min; the untyped break is
    the real lunch here, and it agrees with Flex."""
    got = _classify(
        _timecard(),
        [
            _brk(_at(10), _at(10, 15), "meal", entry_id="SHORT"),   # 15 min
            _brk(_at(12), _at(12, 30), None, entry_id="REAL"),      # 30 min
        ],
        _flex(_at(12), _at(12, 30)),
    )
    assert got is None      # the selected break matches Flex


def test_classification_uses_the_selected_break_not_the_first():
    got = _classify(
        _timecard(),
        [
            _brk(_at(10), _at(10, 10), None, entry_id="TINY"),
            _brk(_at(12), _at(12, 45), "meal", entry_id="MEAL"),
        ],
        _flex(_at(14), _at(14, 45)),
    )
    assert _type_of(got) == "break_time_mismatch"
    assert got[1] == "MEAL"


# ── PFID extraction ──────────────────────────────────────────────────────────

def test_extracts_primary_work_assignment_id():
    worker = {"workAssignments": [
        {"itemID": "A", "primaryIndicator": False},
        {"itemID": "B", "primaryIndicator": True},
    ]}
    assert _primary_work_assignment_id(worker) == "B"


def test_falls_back_to_first_assignment_when_none_flagged_primary():
    worker = {"workAssignments": [{"itemID": "A"}, {"itemID": "B"}]}
    assert _primary_work_assignment_id(worker) == "A"


def test_coerces_numeric_item_id_to_string():
    assert _primary_work_assignment_id({"workAssignments": [{"itemID": 64711919}]}) == "64711919"


@pytest.mark.parametrize("worker", [
    {},
    {"workAssignments": []},
    {"workAssignments": [{}]},
    {"workAssignments": [{"itemID": None}]},
])
def test_missing_assignment_yields_none_rather_than_a_placeholder(worker):
    """A fabricated PFID would make ADP reject every correction for this worker
    with no obvious cause."""
    assert _primary_work_assignment_id(worker) is None
