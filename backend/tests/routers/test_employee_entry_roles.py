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
    """Asserted against the CONSTANT, not create_employee's source.

    EARNED_ROLES moved to module scope so bulk import shares it, and a
    source-scanning test would have failed on the move while the rule was
    intact — and, worse, would have kept passing if the rule were later
    duplicated instead of shared."""

    def test_driver_is_earned(self):
        """ADR-264 — the whole training track is bypassable without this."""
        assert "driver" in employees.EARNED_ROLES

    def test_captain_is_earned(self):
        """ADR-256 treats captaincy as earned through evidence — 'this trainer
        has run a truck 14 times' beats a manager's judgement. Hireable captain
        let a new hire hold a truck's route lead with no record of running one."""
        assert "captain" in employees.EARNED_ROLES

    def test_walker_and_trainer_are_still_earned(self):
        assert {"walker", "trainer"} <= set(employees.EARNED_ROLES)

    def test_field_supervisor_is_NOT_earned(self):
        """Nothing promotes into it, so making it earned leaves it unreachable.
        The reachability test below is what would catch that."""
        assert "field_supervisor" not in employees.EARNED_ROLES

    def test_the_check_is_one_membership_test(self):
        assert "if employee.role in EARNED_ROLES and not onboarding:" in SRC

    def test_each_refusal_names_the_entry_path(self):
        """'You cannot do that' without 'do this instead' sends the manager to
        guess, and they will guess `driver`."""
        assert "Create them as driver_trainee." in employees.EARNED_ROLES["driver"]
        assert "trainees" in employees.EARNED_ROLES["walker"]
        assert "promoted from walkers or trainers" in employees.EARNED_ROLES["captain"]

    def test_driver_trainee_is_not_earned(self):
        """It is the ENTRY point — refusing it would leave no way in."""
        assert "driver_trainee" not in employees.EARNED_ROLES
        assert "trainee" not in employees.EARNED_ROLES


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


class TestBulkImportEnforcesTheSameRule:
    """A second creation path is a second place the rule can be missing.

    `bulk_import_employees` spreads `row.model_dump()` straight into Employee,
    and BulkImportRow.role accepts every value in RoleStr — so before this, a
    CSV could create the driver, walker, trainer and captain accounts that
    create_employee refuses. Silently, one row at a time.

    Found while making captain earned: the change would have been half a rule.
    """

    BULK = inspect.getsource(employees.bulk_import_employees)

    def test_it_checks_the_earned_roles(self):
        assert "if row.role in EARNED_ROLES and not onboarding:" in self.BULK

    def test_it_uses_the_shared_constant_not_a_copy(self):
        """A duplicated list drifts the first time one is edited and not the
        other — which is exactly how captain came to be hireable."""
        assert "EARNED_ROLES = {" not in self.BULK
        assert "EARNED_ROLES[row.role]" in self.BULK

    def test_a_bad_row_is_skipped_not_fatal(self):
        """One bad row in a hundred-row CSV must not discard the ninety-nine
        good ones."""
        i = self.BULK.index("if row.role in EARNED_ROLES and not onboarding:")
        block = self.BULK[i : i + 400]
        assert 'status="skipped"' in block
        assert "continue" in block
        assert "raise" not in block

    def test_the_skip_reason_names_the_entry_path(self):
        i = self.BULK.index("if row.role in EARNED_ROLES and not onboarding:")
        assert "reason=EARNED_ROLES[row.role]" in self.BULK[i : i + 400]

    def test_the_check_precedes_the_insert(self):
        assert self.BULK.index("if row.role in EARNED_ROLES and not onboarding:") < self.BULK.index("db_employee = Employee(")


class TestEveryEarnedRoleStaysReachable:
    """A role refused at hire with no promotion into it is unreachable — the
    failure mode this whole split can most easily create."""

    def test_each_earned_role_has_a_promotion_path(self):
        targets = {dst for dsts in employees.ROLE_TRANSITIONS.values() for dst in dsts}
        for role in employees.EARNED_ROLES:
            assert role in targets, (
                f"{role!r} is refused at hire and nothing promotes into it"
            )

    def test_captain_is_reached_from_walker_or_trainer(self):
        assert "captain" in employees.ROLE_TRANSITIONS["walker"]
        assert "captain" in employees.ROLE_TRANSITIONS["trainer"]
