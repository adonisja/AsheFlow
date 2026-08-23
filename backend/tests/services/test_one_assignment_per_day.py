"""ADR-287 — one assignment per person per day.

THE FAILURE
-----------
Publish to Discord 500'd on staging:

    UniqueViolation: duplicate key value violates unique constraint
    "uq_dispatch_confirmation_employee_date"

One employee was on two trucks that day:

    Falcon | is_hub=f | is_manual=f   <- run_dispatch
    Hub    | is_hub=t | is_manual=t   <- manual drag

The hub was staffed BEFORE the run (possible since ADR-286). At that moment the
employee had no other assignment, so /dispatch/assign's guard correctly allowed
it. Then run_dispatch placed them again — because `get_available_pool` never
excluded people already assigned.

The asymmetry is the tell: `/schedule/available`, the pool the UI offers for
dragging, has had that exclusion all along. Two pools, one rule, one enforcing.

Publish inserts one DispatchConfirmation per assignment row, so the person
appeared twice in a batch a unique constraint rejects — rolling back the WHOLE
publish, not just their row.
"""
import inspect

from app.routers import assignment_members
from app.routers import schedule
from app.services import available_pool


class TestTheDispatchPoolExcludesAssignedStaff:
    SRC = inspect.getsource(available_pool.get_available_pool)

    def test_it_has_the_exclusion(self):
        assert "is_already_assigned" in self.SRC
        assert "~is_already_assigned" in self.SRC

    def test_it_correlates_to_the_outer_employee(self):
        """A correlated EXISTS, not a standalone query — it must ask 'is THIS
        employee assigned', per outer row."""
        i = self.SRC.index("is_already_assigned = (")
        block = self.SRC[i : i + 700]
        assert "AssignmentMember.employee_id == Employee.id" in block
        assert ".exists()" in block

    def test_it_is_scoped_to_the_date(self):
        i = self.SRC.index("is_already_assigned = (")
        block = self.SRC[i : i + 700]
        assert "TruckAssignment.date == target_date" in block

    def test_both_tables_are_company_scoped(self):
        """ADR-115 dim 1 — a join widens the query, so the joined table needs
        its own tenant term."""
        i = self.SRC.index("is_already_assigned = (")
        block = self.SRC[i : i + 700]
        assert "AssignmentMember.company_id == company_id" in block
        assert "TruckAssignment.company_id == company_id" in block


class TestTheTwoPoolsAgree:
    def test_schedule_available_still_has_its_exclusion(self):
        """The pattern this fix mirrors. If it is ever removed, the two pools
        diverge again — which is the whole defect."""
        src = inspect.getsource(schedule.get_available_employees)
        assert "is_already_assigned" in src
        assert "~is_already_assigned" in src

    def test_both_key_on_the_same_three_things(self):
        """employee, date, company. A pool that omits any of them lets someone
        be double-placed."""
        for src in (
            inspect.getsource(available_pool.get_available_pool),
            inspect.getsource(schedule.get_available_employees),
        ):
            i = src.index("is_already_assigned = (")
            block = src[i : i + 700]
            assert "AssignmentMember.employee_id == Employee.id" in block
            assert "TruckAssignment.date ==" in block
            assert "TruckAssignment.company_id ==" in block


class TestTheOpenEndpointIsGuarded:
    SRC = inspect.getsource(assignment_members.create_assignment_member)

    def test_it_refuses_a_second_assignment_that_date(self):
        """It checked yesterday's truck and ban conflicts, but filtered by
        assignment_id alone — so Falcon + Hub was allowed."""
        assert "already_assigned" in self.SRC
        assert "TruckAssignment.date == assignment.date" in self.SRC

    def test_it_returns_409_naming_the_rule(self):
        i = self.SRC.index("if already_assigned:")
        block = self.SRC[i : i + 500]
        assert "HTTP_409_CONFLICT" in block
        assert "one assignment per person" in block

    def test_the_check_precedes_the_insert(self):
        assert self.SRC.index("already_assigned = (") < self.SRC.index("db_member = AssignmentMember(")

    def test_it_is_company_scoped(self):
        i = self.SRC.index("already_assigned = (")
        block = self.SRC[i : i + 600]
        assert "AssignmentMember.company_id == caller.company_id" in block
        assert "TruckAssignment.company_id == caller.company_id" in block


class TestPublishHandlesTheConstraintViolation:
    """ADR-287 — the failure mode the operator actually saw.

    Nothing caught the IntegrityError. It escaped to the ASGI layer and killed
    the response mid-flight, so with Caddy in front the browser saw a DROPPED
    CONNECTION and the UI reported "Couldn't reach the server" — an accurate
    description of what the client observed, and a completely misleading
    account of what went wrong.

    The traceback existed only in the server log. That is a bad place for the
    single copy of the truth: the operator had no way to reach it.
    """

    @staticmethod
    def _src():
        import inspect

        from app.routers import dispatch

        return inspect.getsource(dispatch.publish_dispatch)

    def test_the_confirmation_commit_is_guarded(self):
        src = self._src()
        assert "except IntegrityError:" in src

    def test_it_rolls_back(self):
        """Without a rollback the session stays poisoned and every later query
        in the request fails with InFailedSqlTransaction."""
        src = self._src()
        i = src.index("except IntegrityError:")
        assert "db.rollback()" in src[i : i + 200]

    def test_it_raises_409_not_500(self):
        """A 500 that kills the connection is indistinguishable from a network
        failure AT THE CLIENT. A 409 arrives intact and says what happened."""
        src = self._src()
        i = src.index("except IntegrityError:")
        assert "HTTP_409_CONFLICT" in src[i : i + 1600]

    def test_the_message_names_who_is_double_assigned(self):
        """'Cannot publish' alone sends the dispatcher hunting across every
        truck. The whole point is to name the person."""
        src = self._src()
        assert "is assigned to more than one truck on" in src
        assert "Remove the extra assignment and publish again." in src

    def test_it_falls_back_when_no_duplicate_is_found(self):
        """The constraint can also fire on a genuine race — two publishes at
        once. Then there is no duplicate assignment to name, and a message
        claiming one would be wrong."""
        src = self._src()
        assert "a confirmation already exists for" in src

    def test_the_duplicate_lookup_is_company_scoped(self):
        """ADR-115 dim 1 — three joined tables, three tenant terms."""
        src = self._src()
        i = src.index("except IntegrityError:")
        block = src[i : i + 1400]
        assert block.count("company_id == caller.company_id") == 3

    def test_it_logs_without_naming_anyone(self):
        """ADR-221 — the log records the COUNT; the name goes to the caller who
        is already authorised to see their own crew."""
        src = self._src()
        i = src.index("except IntegrityError:")
        block = src[i : i + 1400]
        assert "logger.warning" in block
        assert "duplicates=%d" in block
        assert "%s" not in block.split("logger.warning")[1][:200].replace("date=%s", "").replace("company=%s", "")
