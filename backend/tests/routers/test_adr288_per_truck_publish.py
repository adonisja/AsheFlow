"""ADR-288 — publishing is per truck.

THE FAILURE THIS REMOVES
------------------------
`publish_dispatch` refused the whole day if ANY truck had moved past `planned`:

    statuses = {a.status for a in assignments}
    if statuses - {"planned"}:
        raise HTTPException(409, "Dispatch has already been published...")

So publishing one truck individually made the day-level button 409 for every
remaining truck — the two controls were mutually exclusive. The operator's
requirement is the opposite: a truck published on its own is SKIPPED by
publish-all, while publish-all does not stop a truck's own button working.

dispatch.py is proprietary; CI copies it in before pytest, so there is
deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


PUB = _code_only(dispatch.publish_dispatch)
FIN = _code_only(dispatch.finalize_dispatch)
ASSIGN = _code_only(dispatch.manual_assignment)


class TestPublishScopesToPlanned:
    def test_it_filters_rather_than_refusing(self):
        assert 'assignments = [a for a in assignments if a.status == "planned"]' in PUB

    def test_the_old_whole_day_refusal_is_gone(self):
        """`statuses - {"planned"}` is what made the two controls exclusive."""
        assert 'statuses - {"planned"}' not in PUB

    def test_it_still_refuses_when_nothing_is_publishable(self):
        """A filter matching nothing must say so. Returning 200 having done
        nothing is worse than the old 409 — the dispatcher cannot tell
        'already done' from 'just worked'."""
        assert "if not assignments:" in PUB
        i = PUB.index('assignments = [a for a in assignments if a.status == "planned"]')
        assert "already been published" in PUB[i : i + 700]

    def test_it_reports_what_it_skipped(self):
        assert "already_published" in PUB
        assert '"trucks_skipped"' in PUB
        assert '"trucks_published"' in PUB


class TestFinalizeScopesToActive:
    def test_it_filters_to_active(self):
        assert 'assignments = [a for a in assignments if a.status == "active"]' in FIN

    def test_the_old_whole_day_refusal_is_gone(self):
        assert '"completed" in fin_statuses' not in FIN

    def test_it_distinguishes_all_done_from_never_published(self):
        """Two different situations; one message for both sends the dispatcher
        to the wrong place."""
        assert "already been posted for every truck" in FIN
        assert "must be published to Discord" in FIN

    def test_the_exception_path_requery_keeps_the_filter(self):
        """THE subtle one. The captain-familiarity rollback re-queries
        assignments; without re-applying `status == active` it widens back to
        every truck and the flip below re-stamps already-completed rows.
        Only reachable through an exception, which is why it would survive
        ordinary testing."""
        i = FIN.index("assignments = db.query(TruckAssignment).filter(")
        j = FIN.rindex("assignments = db.query(TruckAssignment).filter(")
        assert i != j, "expected two queries — the initial one and the re-query"
        assert 'TruckAssignment.status == "active"' in FIN[j : j + 400]


class TestLateAdditionReadsItsOwnTruck:
    def test_the_phase_is_the_trucks_not_the_days(self):
        assert 'dispatch_phase = truck_assignment.status or "planned"' in ASSIGN

    def test_the_day_level_derivation_is_gone(self):
        """It notified someone added to a PLANNED truck because a DIFFERENT
        truck had published."""
        assert "date_statuses" not in ASSIGN

    def test_a_finalized_truck_refuses_plain_assignment(self):
        """ADR-288 D3 — after finalize, crew changes are transfers. A member
        added here would hold a pending confirmation nothing could resolve, on
        a truck whose Discord roster is already posted."""
        guard = 'if (truck_assignment.status or "planned") == "completed":'
        assert guard in ASSIGN
        i = ASSIGN.index(guard)
        window = ASSIGN[i : i + 600]
        assert "HTTP_409_CONFLICT" in window
        assert "truck transfer" in window

    def test_the_refusal_names_the_alternative(self):
        """'You cannot do that' without 'do this instead' sends the dispatcher
        to guess."""
        src = inspect.getsource(dispatch.manual_assignment)
        assert "final crew is already posted" in src
        assert "notifies them, updates Discord" in src

    def test_the_refusal_precedes_the_insert(self):
        """Found by this test on its first run: the refusal sat AFTER the
        AssignmentMember was created, so the endpoint built a row and then 409'd.
        No commit ran in between, so the insert rolled back — but correctness
        depended on 'nothing commits here', which a later edit could break
        silently. The guard now sits beside the other duplicate-prevention
        checks, right after the assignment is resolved."""
        guard = 'if (truck_assignment.status or "planned") == "completed":'
        assert ASSIGN.index(guard) < ASSIGN.index("new_member = AssignmentMember(")
