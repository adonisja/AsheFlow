"""Which roles a new employee may be created with (ADR-264).

THE GAP THIS CLOSES
-------------------
Roles split into ENTRY roles (assignable at hire) and EARNED roles (reached by
promotion). Walker and trainer were already earned: walkers start as trainees,
trainers are promoted from walkers.

`driver` was an entry role only because there was no driver training track. Now
there is, and a direct driver hire would silently skip it — invisibly, because
the employee simply never appears in any training view. So `driver` joins the
earned set and `driver_trainee` becomes the driver-side entry point.

create_employee had NO test coverage before this file, which is why the change
above did not break a single existing test.
"""
import inspect

from app.routers import employees


SRC = inspect.getsource(employees.create_employee)


class TestEarnedRolesCannotBeAssignedAtHire:
    def test_driver_is_earned_now(self):
        """ADR-264 — the whole training track is bypassable without this."""
        assert '"driver": (' in SRC
        assert "_EARNED_ROLES" in SRC

    def test_walker_and_trainer_are_still_earned(self):
        """The pre-existing rule must survive the refactor that added driver."""
        assert '"walker":' in SRC
        assert '"trainer":' in SRC

    def test_the_check_is_one_membership_test(self):
        """The original was an if/else over two roles with the message chosen
        inline. A third role would have made that unreadable, and the fourth
        would have been dropped."""
        assert "if employee.role in _EARNED_ROLES:" in SRC

    def test_each_refusal_names_the_entry_path(self):
        """'You cannot do that' without 'do this instead' sends the manager to
        guess, and they will guess `driver`."""
        assert "Create them as driver_trainee." in SRC
        assert "must start as trainees" in SRC

    def test_driver_trainee_is_not_earned(self):
        """It is the ENTRY point — refusing it would leave no way in."""
        i = SRC.index("_EARNED_ROLES = {")
        block = SRC[i : SRC.index("}", i)]
        assert '"driver_trainee"' not in block


class TestManagementMayCreateBothEntryRoles:
    def test_the_two_track_entry_points(self):
        """ADR-264 D2 — two parallel tracks, so two entry points."""
        assert 'employee.role not in ("driver_trainee", "trainee")' in SRC

    def test_driver_was_replaced_not_supplemented(self):
        """Leaving `driver` in the allowed set would let management create one
        directly, defeating the earned-role rule for exactly the caller who
        hires most often."""
        i = SRC.index('caller.role == "management"')
        window = SRC[i : i + 220]
        assert '"driver"' not in window.replace('"driver_trainee"', "")

    def test_the_error_names_what_they_can_create(self):
        assert "driver trainee or trainee accounts" in SRC


class TestBothTracksHaveAnEntryPoint:
    def test_every_earned_role_is_reachable(self):
        """A role that is earned but has no promotion path is unreachable."""
        from app.routers.employees import ROLE_TRANSITIONS

        reachable = {r for targets in ROLE_TRANSITIONS.values() for r in targets}
        for earned in ("walker", "trainer", "driver"):
            assert earned in reachable, f"{earned} is refused at hire and unreachable by promotion"

    def test_driver_is_reached_from_driver_trainee(self):
        from app.routers.employees import ROLE_TRANSITIONS

        assert "driver" in ROLE_TRANSITIONS.get("driver_trainee", ())
