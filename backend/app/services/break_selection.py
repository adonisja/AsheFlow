"""Choose which ADP break to reconcile against Amazon Flex (ADR-233).

Workforce Now reports breaks explicitly — timeEntries[].breaks[], "Meal times"
in ADP's own schema — and an employee's day can carry several: a meal, one or
more rest breaks, sometimes a split. AsheFlow reconciles exactly one window
against Flex, so it has to choose.

RUN had no such field. It inferred the break from the first gap of 30 minutes or
more between clock-out and the next clock-in. That algorithm must not be carried
over: under WFN it would treat any long non-break gap — a split shift, unpaid
downtime, a mid-route clock-out — as a meal and propose it as a payroll
correction. Wrong output, no error.

Pure functions, no database: the rule is the part most likely to be wrong, so it
is kept where it can be exercised directly.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

# A meal must be at least this long to be the break AsheFlow reconciles. Shorter
# breaks are still surfaced (as break_short_in_adp) — they are a finding, not a
# comparison candidate.
MIN_QUALIFYING_BREAK = timedelta(minutes=30)

# breaks[].breakTypeCode.codeValue for a meal. ADP documents the vocabulary as
# "e.g. meal, rest etc" without pinning literals, and real DSP data has not been
# observed yet — hence a constant, so sandbox can correct it in one place.
MEAL_TYPE_CODE = "meal"


@dataclass(frozen=True)
class BreakCandidate:
    """One ADP break, flattened out of the ORM for selection.

    Mirrors ADPTimeCardBreak but stays independent of it so the rule can be
    tested without a session.
    """
    adp_entry_id: str
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    break_type_code: Optional[str] = None
    break_item_id: Optional[str] = None

    @property
    def duration(self) -> Optional[timedelta]:
        """None when either bound is missing — an unbounded break has no length.

        ADP can report a break mid-shift with no end time yet, so this is an
        expected state, not corruption.
        """
        if self.start_at is None or self.end_at is None:
            return None
        return self.end_at - self.start_at

    @property
    def is_meal(self) -> bool:
        return (self.break_type_code or "").strip().lower() == MEAL_TYPE_CODE

    @property
    def is_qualifying(self) -> bool:
        d = self.duration
        return d is not None and d >= MIN_QUALIFYING_BREAK


@dataclass(frozen=True)
class BreakSelection:
    """The chosen break, plus why it was chosen.

    `qualifying` distinguishes "this is the break to compare against Flex" from
    "this is the best of a bad set, and the finding is that it is too short" —
    the caller needs both to pick a finding_type.
    """
    candidate: Optional[BreakCandidate]
    qualifying: bool

    @property
    def found(self) -> bool:
        return self.candidate is not None


def select_break(breaks: Sequence[BreakCandidate]) -> BreakSelection:
    """Pick the break to reconcile, per the agreed rule.

    1. Meal-typed and >= 30 min  -> the first such break.
    2. Else the longest break of any type that is >= 30 min.
    3. Else the longest break of any type      -> selected, not qualifying.
    4. Else (nothing measurable)               -> nothing selected.

    Note that the duration gate applies to meal-typed breaks too: a 15-minute
    meal break does not win on type alone. It falls through to rule 2, where an
    untyped or rest-typed break may well be the real lunch.

    "First" in rule 1 means first in the order given, which the caller supplies
    chronologically. Rules 2 and 3 break ties by taking the earliest of the
    longest, so the result is deterministic rather than dependent on sort
    stability.
    """
    measurable = [b for b in breaks if b.duration is not None]
    if not measurable:
        return BreakSelection(candidate=None, qualifying=False)

    for candidate in measurable:
        if candidate.is_meal and candidate.is_qualifying:
            return BreakSelection(candidate=candidate, qualifying=True)

    longest = max(measurable, key=lambda b: b.duration)

    return BreakSelection(candidate=longest, qualifying=longest.is_qualifying)
