"""Decline analysis and its volume gate (ADR-268).

WHY THE GATE EXISTS
A decline rate is ambiguous on its own — "declined 4 of 12" reads the same
whether someone is unreliable or is repeatedly handed a shift they cannot make.
Clustering disambiguates it: four declines all on Fridays is a ROTA signal, and
the fix is to stop rostering that person on Fridays.

But clustering needs observations. The operator set the bar: a weekday slice
reports a bare COUNT until that weekday has been seen at least four times —
roughly a month — so a pattern has to persist rather than reflect one bad week.

`rate` is None below the gate rather than 0.0, so a consumer rendering
`rate ?? count` cannot accidentally publish a 1-sample percentage as a finding.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.dispatch_confirmation import DispatchConfirmation
from app.services.decline_analysis import (
    MIN_SAMPLE, MIN_WEEKDAY_OCCURRENCES, get_decline_analysis,
)
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_truck,
)


def _conf(db, employee, when, status):
    db.add(DispatchConfirmation(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=employee.id,
        date=when, status=status, source="manual",
    ))
    db.commit()


def _fridays(n):
    """The n most recent Fridays, oldest first."""
    d = date.today()
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return [d - timedelta(weeks=i) for i in reversed(range(n))]


class TestWeekdayGate:
    def test_three_fridays_report_a_count_not_a_rate(self, db):
        """Below a full cycle the pattern could be one bad week. A percentage
        would be quoted as a finding; a count cannot be."""
        emp = make_employee(db, role="walker", name="Fri Decliner")
        for d in _fridays(3):
            _conf(db, emp, d, "declined")

        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=60), date.today())
        fri = next(s for s in a.by_weekday if s.key == "Friday")
        assert fri.occurrences == 3
        assert fri.declines == 3
        assert fri.gated is True
        assert fri.rate is None, "a 3-sample rate was published"

    def test_four_fridays_clear_the_gate(self, db):
        emp = make_employee(db, role="walker", name="Fri Decliner")
        for d in _fridays(4):
            _conf(db, emp, d, "declined")

        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=60), date.today())
        fri = next(s for s in a.by_weekday if s.key == "Friday")
        assert fri.occurrences == MIN_WEEKDAY_OCCURRENCES
        assert fri.gated is False
        assert fri.rate == pytest.approx(1.0)

    def test_the_gate_counts_WEEKDAYS_not_confirmations(self, db):
        """12 confirmations across 2 Fridays is not 12 observations of Friday.
        Counting rows instead of dates would clear the gate on a fortnight."""
        emp1 = make_employee(db, role="walker", name="A")
        emp2 = make_employee(db, role="walker", name="B")
        emp3 = make_employee(db, role="walker", name="C")
        for d in _fridays(2):
            for e in (emp1, emp2, emp3):
                _conf(db, e, d, "declined")

        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=60), date.today())
        fri = next(s for s in a.by_weekday if s.key == "Friday")
        assert fri.total == 6          # plenty of rows
        assert fri.occurrences == 2    # but only two Fridays
        assert fri.gated is True

    def test_the_threshold_is_the_operators_full_cycle(self):
        assert MIN_WEEKDAY_OCCURRENCES == 4


class TestClustering:
    def test_declines_attribute_to_the_truck_they_were_rostered_on(self, db):
        """'This shift keeps getting refused' is only answerable if a decline
        points at a truck."""
        when = _fridays(1)[0]
        emp = make_employee(db, role="walker", name="On Viking")
        truck = make_truck(db, name="Viking")
        a = make_assignment(db, truck, target_date=when)
        make_member(db, a, emp, "walker")
        _conf(db, emp, when, "declined")

        res = get_decline_analysis(db, SEED_COMPANY_ID,
                                   when - timedelta(days=1), when)
        viking = next(s for s in res.by_truck if s.key == "Viking")
        assert viking.declines == 1

    def test_a_decline_with_no_roster_row_is_not_attributed_to_a_truck(self, db):
        """Better absent than attributed to the wrong vehicle."""
        when = _fridays(1)[0]
        emp = make_employee(db, role="walker", name="No Truck")
        _conf(db, emp, when, "declined")
        res = get_decline_analysis(db, SEED_COMPANY_ID,
                                   when - timedelta(days=1), when)
        assert res.by_truck == []
        assert res.total_declines == 1     # still counted overall

    def test_confirmations_are_counted_in_the_denominator(self, db):
        """A rate needs both halves — declines alone cannot produce one."""
        emp = make_employee(db, role="walker", name="Mostly Yes")
        fris = _fridays(4)
        _conf(db, emp, fris[0], "declined")
        for d in fris[1:]:
            _conf(db, emp, d, "confirmed")

        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=60), date.today())
        fri = next(s for s in a.by_weekday if s.key == "Friday")
        assert fri.total == 4
        assert fri.declines == 1
        assert fri.rate == pytest.approx(0.25)


class TestOrderingAndScope:
    def test_gated_slices_sort_last(self, db):
        """A slice with no rate cannot be ranked against one that has a rate;
        floating it up on decline count alone is the noise the gate suppresses."""
        emp = make_employee(db, role="walker", name="Mixed")
        for d in _fridays(4):
            _conf(db, emp, d, "confirmed")
        # Tuesday: seen once, so gated
        tue = date.today()
        while tue.weekday() != 1:
            tue -= timedelta(days=1)
        _conf(db, emp, tue, "declined")

        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=60), date.today())
        assert a.by_weekday[-1].gated is True

    def test_no_confirmations_is_an_empty_result(self, db):
        a = get_decline_analysis(db, SEED_COMPANY_ID,
                                 date.today() - timedelta(days=5), date.today())
        assert a.total_confirmations == 0
        assert a.by_weekday == []

    def test_another_company_is_never_included(self, db):
        emp = make_employee(db, role="walker", name="Ours")
        _conf(db, emp, date.today(), "declined")
        a = get_decline_analysis(db, uuid.uuid4(),
                                 date.today() - timedelta(days=5), date.today())
        assert a.total_confirmations == 0

    def test_the_person_gate_uses_sample_size_not_weekdays(self):
        """A person is not a weekly cycle, so counting distinct dates would be
        the wrong unit for them."""
        assert MIN_SAMPLE == 10
