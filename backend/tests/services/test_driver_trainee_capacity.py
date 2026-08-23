"""ADR-264 D6 — a driver trainee consumes one truck and TWO drivers.

TWO FAILURES, ONE OF THEM SILENT
--------------------------------
1. `driver_trainee` was absent from the role filter in get_available_pool's
   SQL, so an active, scheduled driver trainee never entered the pool at all.
   Not a bucketing miss — they were excluded by the query, with no warning.
   That is how someone works a whole program with no training records and
   nobody finds out.

2. The driver shortage check compared `num_drivers < num_trucks`. A trainee and
   their supervisor take one truck and two drivers, so the requirement is
   `trucks + driver_trainees`. Under-counting by one leaves a truck unstaffed,
   discovered at dispatch.
"""
import inspect

from app.services import available_pool as ap
from app.services import run_dispatch as rd


class TestTheTraineeReachesThePool:
    def test_the_role_filter_includes_driver_trainee(self):
        """The SQL filter, not the bucketing — this is where they were lost."""
        src = inspect.getsource(ap.get_available_pool)
        i = src.index("Employee.role.in_(")
        assert '"driver_trainee"' in src[i : i + 260]

    def test_they_get_their_own_bucket(self):
        src = inspect.getsource(ap.get_available_pool)
        assert '"driver_trainees": []' in src
        assert 'available_pool["driver_trainees"].append(employee)' in src

    def test_they_are_not_folded_into_drivers(self):
        """Counting them as drivers would hide the shortfall exactly when it
        exists: they are the ones creating the extra demand."""
        src = inspect.getsource(ap.get_available_pool)
        i = src.index('elif employee.role == "driver_trainee"')
        assert 'available_pool["drivers"]' not in src[i : i + 160]


class TestCapacityCountsThePair:
    def test_demand_is_trucks_plus_trainees(self):
        src = inspect.getsource(rd.run_dispatch)
        assert "drivers_needed = num_trucks + num_driver_trainees" in src

    def test_the_comparison_uses_the_adjusted_demand(self):
        """`num_drivers < num_trucks` is the bug."""
        src = inspect.getsource(rd.run_dispatch)
        assert "if num_drivers < drivers_needed:" in src
        assert "if num_drivers < num_trucks:" not in src

    def test_trainees_are_not_counted_as_supply(self):
        src = inspect.getsource(rd.run_dispatch)
        # The supply LINE only. The trainee count sits on the next line, so a
        # window spanning both proves nothing.
        line = next(
            ln for ln in src.splitlines() if ln.strip().startswith("num_drivers = len(")
        )
        assert 'available_pool["drivers"]' in line
        assert "driver_trainees" not in line

    def test_the_warning_explains_why_more_drivers_are_needed(self):
        """A dispatcher reading '3 needed for 2 trucks' with no explanation
        would assume the count is wrong."""
        src = inspect.getsource(rd.run_dispatch)
        assert "each need a supervising" in src

    def test_the_note_is_omitted_when_there_are_no_trainees(self):
        """On an ordinary day the message must read exactly as before."""
        src = inspect.getsource(rd.run_dispatch)
        assert 'if num_driver_trainees else ""' in src
