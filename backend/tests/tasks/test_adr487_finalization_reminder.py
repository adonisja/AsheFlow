"""The finalization reminder names the trucks and reads the real deadline (ADR-487).

THE FIFTH HELD DEFECT, AND IT WAS THREE
=======================================

Recorded at design time as "does not name the unfinalized trucks". Reading the
task found two more in the same block:

    has_dispatch = db.query(TruckAssignment).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date == today,
    ).first()                      # <-- existence only
    if not has_dispatch:
        continue

    message = (
        f"⏰ Dispatch finalization deadline is at 09:10 AM. ..."   # <-- hardcoded
    )

1. The query asks whether ANY assignment exists, so it cannot name the trucks.
2. It therefore fires at a dispatcher who finalised everything at 08:00.
3. The deadline is hardcoded while CompanyConfig.dispatch_confirmation_cutoff is
   a configurable Time — wrong for any tenant that changed it.

The third compounds: that column is a NAIVE Time documented as "read in the
company's own timezone", so rendering it needs company_datetime (ADR-486), not
strftime on a bare value.
"""
from __future__ import annotations

import inspect
from datetime import datetime

import pytest

from tests.conftest import code_only

from app.tasks import dispatch_alerts as A


class TestItNamesTheUnfinalizedTrucks:
    def test_the_query_selects_unfinalized_not_merely_existing(self):
        """`.first()` on "any assignment today" cannot produce a truck list, and
        it is why the reminder fired at a station with nothing outstanding."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert 'TruckAssignment.status != "completed"' in src, (
            "the reminder must select UNFINALIZED assignments; 'completed' is "
            "the status finalize_dispatch sets"
        )

    def test_it_joins_truck_to_get_a_name(self):
        """TruckAssignment has truck_id, not truck_name."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "Truck.name" in src
        assert "TruckAssignment.truck_id == Truck.id" in src

    def test_the_join_is_tenant_scoped_on_both_sides(self):
        """Dimension 1. A join adds a second table, and a filter on one side
        does not scope the other."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "TruckAssignment.company_id == company_id" in src
        assert "Truck.company_id == company_id" in src

    def test_a_company_with_nothing_outstanding_is_skipped(self):
        """The defect that made this a nag: a dispatcher who finalised at 08:00
        was still told to go and finalise."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "if not unfinalized:" in src
        assert "continue" in src

    def test_the_truck_list_is_capped(self):
        """A station with thirty outstanding trucks needs a count, not thirty
        names in a notification body."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "truck_names[:8]" in src
        assert "more" in src


class TestItReadsTheConfiguredDeadline:
    def test_no_hardcoded_time_remains(self):
        """The literal that was wrong for any tenant that changed the cutoff.

        code_only, because the comment above the fix NAMES the old hardcoded
        time to explain what was removed — the fifth time an absence assertion
        in this repo has matched its own explanation.
        """
        assert "09:10" not in code_only(A.alert_finalization_deadline), (
            "the deadline must come from CompanyConfig, not a literal"
        )

    def test_it_reads_dispatch_confirmation_cutoff(self):
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "dispatch_confirmation_cutoff" in src
        assert "get_company_config" in src

    def test_the_cutoff_is_rendered_in_company_time(self):
        """It is a naive Time column documented as "read in the company's own
        timezone", so strftime on the bare value would render it as though the
        server's zone were the tenant's (ADR-486)."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "company_datetime(tz, today, cutoff)" in src

    def test_a_null_cutoff_does_not_produce_a_sentence_about_None(self):
        """The column is nullable with no server_default — the "default 09:00"
        on it is a COMMENT. Saying "at None" is worse than saying nothing, and
        inventing 09:10 is the defect being fixed."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "if cutoff is not None:" in src
        assert '"soon"' in src


class TestTheTimeFormatIsPortable:
    """`%-I` strips the leading zero but is a glibc/BSD extension, not standard,
    and raises on a musl-based image. The code uses %I plus lstrip instead."""

    def test_no_nonstandard_strftime_directive(self):
        # code_only: the comment explaining the choice names %-I.
        assert "%-I" not in code_only(A.alert_finalization_deadline), (
            "%-I is a glibc/BSD extension; use %I with lstrip('0')"
        )

    @pytest.mark.parametrize("hour,minute,expected", [
        (9, 10, "9:10 AM"),
        (12, 0, "12:00 PM"),    # noon must not become 2:00 PM
        (13, 5, "1:05 PM"),
        (0, 30, "12:30 AM"),    # midnight must not lose its hour
    ])
    def test_the_strip_is_safe_at_every_boundary(self, hour, minute, expected):
        """%I is always two digits 01-12, so lstrip('0') removes at most one
        character and never touches 10/11/12."""
        got = datetime(2026, 10, 5, hour, minute).strftime("%I:%M %p").lstrip("0")
        assert got == expected


class TestTheMessageSaysWhatToDo:
    def test_it_states_the_count_and_the_action(self):
        """D10's rule: an ACTION message says what to do. This one also has to
        say which trucks, which was the original finding."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert "not finalized:" in src
        assert "Finalize" in src

    def test_singular_and_plural_are_both_handled(self):
        """"1 trucks not finalized" is the kind of detail that makes an alert
        look generated rather than written."""
        src = inspect.getsource(A.alert_finalization_deadline)
        assert 'noun = "truck" if len(truck_names) == 1 else "trucks"' in src
