"""Break selection rule (ADR-233 Phase 4).

The chosen break becomes a proposed payroll correction, so picking the wrong one
is not a display bug. These pin the ordered rule:

  1. meal-typed and >= 30 min -> first such
  2. else longest of any type >= 30 min
  3. else longest of any type, marked not-qualifying
  4. else nothing
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.break_selection import (
    MEAL_TYPE_CODE,
    MIN_QUALIFYING_BREAK,
    BreakCandidate,
    select_break,
)


def _at(hour, minute=0):
    return datetime(2026, 7, 24, hour, minute, tzinfo=timezone.utc)


def _brk(start, end, type_code=None, entry_id="E1"):
    return BreakCandidate(
        adp_entry_id=entry_id,
        start_at=start,
        end_at=end,
        break_type_code=type_code,
    )


# ── rule 1: meal-typed and long enough ───────────────────────────────────────

def test_prefers_qualifying_meal_over_a_longer_rest():
    """Type wins over length — once the meal clears the duration gate."""
    rest = _brk(_at(10), _at(11), "rest")          # 60 min
    meal = _brk(_at(12), _at(12, 35), "meal")      # 35 min
    got = select_break([rest, meal])
    assert got.candidate is meal
    assert got.qualifying is True


def test_takes_the_first_qualifying_meal_when_several():
    first = _brk(_at(11), _at(11, 30), "meal")
    second = _brk(_at(15), _at(16), "meal")        # longer, but later
    assert select_break([first, second]).candidate is first


def test_meal_type_match_is_case_insensitive():
    assert select_break([_brk(_at(12), _at(12, 30), "Meal")]).qualifying is True
    assert select_break([_brk(_at(12), _at(12, 30), " MEAL ")]).qualifying is True


def test_exactly_thirty_minutes_qualifies():
    """The gate is >= 30, not > 30."""
    got = select_break([_brk(_at(12), _at(12, 30), "meal")])
    assert got.qualifying is True


# ── rule 2: the duration gate applies to meals too ───────────────────────────

def test_short_meal_does_not_win_on_type_alone():
    """A 15-minute meal falls through — an untyped break may be the real lunch.
    This is the case most likely to be got wrong."""
    short_meal = _brk(_at(10), _at(10, 15), "meal")   # 15 min
    untyped = _brk(_at(12), _at(12, 45))              # 45 min
    got = select_break([short_meal, untyped])
    assert got.candidate is untyped
    assert got.qualifying is True


def test_falls_back_to_longest_qualifying_when_no_meal_type_present():
    short = _brk(_at(10), _at(10, 31))     # 31 min
    long = _brk(_at(12), _at(13))          # 60 min
    got = select_break([short, long])
    assert got.candidate is long
    assert got.qualifying is True


def test_rest_break_can_be_selected_when_no_meal_qualifies():
    rest = _brk(_at(12), _at(12, 40), "rest")
    got = select_break([rest])
    assert got.candidate is rest
    assert got.qualifying is True


# ── rule 3: nothing long enough ──────────────────────────────────────────────

def test_selects_longest_but_flags_not_qualifying_when_all_short():
    """Both systems may still disagree about a short break, so a candidate is
    returned — but the caller must know it is under the threshold."""
    a = _brk(_at(10), _at(10, 10))    # 10 min
    b = _brk(_at(12), _at(12, 25))    # 25 min
    got = select_break([a, b])
    assert got.candidate is b
    assert got.qualifying is False


def test_short_meal_alone_is_selected_but_not_qualifying():
    meal = _brk(_at(12), _at(12, 20), "meal")
    got = select_break([meal])
    assert got.candidate is meal
    assert got.qualifying is False


# ── rule 4: nothing measurable ───────────────────────────────────────────────

def test_no_breaks_selects_nothing():
    got = select_break([])
    assert got.found is False
    assert got.candidate is None
    assert got.qualifying is False


def test_unbounded_breaks_are_not_selectable():
    """ADP can report a break mid-shift with no end time. It has no length, so
    it cannot be compared against Flex."""
    open_ended = _brk(_at(12), None, "meal")
    no_start = _brk(None, _at(12, 30), "meal")
    assert select_break([open_ended, no_start]).found is False


def test_ignores_unbounded_but_still_picks_a_measurable_one():
    open_ended = _brk(_at(9), None, "meal")
    real = _brk(_at(12), _at(12, 35), "meal")
    assert select_break([open_ended, real]).candidate is real


# ── determinism ──────────────────────────────────────────────────────────────

def test_ties_resolve_to_the_earliest_of_the_longest():
    """Two equal-length breaks must not select differently run to run."""
    first = _brk(_at(10), _at(10, 40), entry_id="A")
    second = _brk(_at(14), _at(14, 40), entry_id="B")
    assert select_break([first, second]).candidate.adp_entry_id == "A"
    # order of input does not change which wins on tie
    assert select_break([second, first]).candidate.adp_entry_id == "B"


def test_selection_carries_the_entry_id_the_write_needs():
    """The correction is addressed to ADP by the parent entryID."""
    got = select_break([_brk(_at(12), _at(12, 30), "meal", entry_id="8672975228284578|1")])
    assert got.candidate.adp_entry_id == "8672975228284578|1"


# ── constants ────────────────────────────────────────────────────────────────

def test_threshold_and_meal_code_are_the_agreed_values():
    assert MIN_QUALIFYING_BREAK == timedelta(minutes=30)
    assert MEAL_TYPE_CODE == "meal"


@pytest.mark.parametrize("code", [None, "", "   ", "rest", "other"])
def test_non_meal_codes_are_not_treated_as_meals(code):
    assert _brk(_at(12), _at(12, 30), code).is_meal is False
