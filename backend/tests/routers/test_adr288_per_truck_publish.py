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
# swap_assignment is the OTHER write path onto a truck (drag between trucks).
# It carried its own copy of the day-level phase scan; D3/D5 below cover it.
SWAP = _code_only(dispatch.swap_assignment)


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


class TestAssignPhaseIsPerTruck:
    """ADR-288 D3 — a live bug found while implementing D5.

    `manual_assignment` derived the phase from EVERY TruckAssignment on the
    date and took the furthest-along status any of them had:

        date_statuses = {row.status for row in db.query(TruckAssignment)...}
        if "completed" in date_statuses: dispatch_phase = "completed"

    Correct while publishing was day-level and all trucks moved in lockstep.
    Under per-truck publishing it misfires: with truck A completed and truck B
    still planned, dropping someone onto B took the "completed" branch — DM'ing
    them "you've been assigned for today", granting B's Discord channel, and
    skipping the confirmation reset, for a truck nobody had published.
    """

    def test_phase_reads_the_destination_trucks_own_status(self):
        assert 'dispatch_phase = destination_assignment.status or "planned"' in SWAP

    def test_the_date_wide_scan_is_gone(self):
        assert "date_statuses" not in SWAP

    def test_no_other_truck_on_the_date_is_consulted(self):
        """The whole point: one other truck's status must not reach this
        decision. Any surviving query over TruckAssignment-by-date in the
        phase derivation would reintroduce it."""
        i = SWAP.index("dispatch_phase =")
        window = SWAP[max(0, i - 500) : i + 200]
        assert "TruckAssignment.date" not in window


class TestCrewChangeReachesTheChannel:
    """ADR-288 D5, as SUPERSEDED by ADR-295.

    D5 originally posted a *correction* embed beside the stale roster, because
    the bot had not kept the crew embed's message id. ADR-295 found that claim
    was based on the wrong endpoint — the crew embeds already `await` their
    send — and replaced the correction with an in-place EDIT plus a chat notice.

    What survives from D5 unchanged is the REQUIREMENT: a crew change on a
    published truck must reach the truck's channel, not just the individual's
    DMs, and must not be gated on the employee having a Discord account. Those
    are asserted here; the edit mechanics live in test_adr295_crew_embed_edit.
    """

    def test_a_change_on_an_active_truck_reaches_the_channel(self):
        assert "_fire_crew_embed_update(" in SWAP

    def test_it_is_sent_for_employees_with_no_discord_account(self):
        """Guarded on `discord_id` it would skip exactly the case the channel
        most needs told about — a crew member the bot cannot DM."""
        i = SWAP.index("_fire_crew_embed_update(")
        guard_line = SWAP[:i].rstrip().splitlines()[-1]
        assert 'if dispatch_phase == "active":' in guard_line
        assert "discord_id" not in guard_line

    def test_it_targets_the_destination_truck(self):
        i = SWAP.index("_fire_crew_embed_update(")
        assert "truck=destination_truck" in SWAP[i : i + 400]

    def test_completed_trucks_are_left_to_the_transfer_system(self):
        """A completed truck routes through transfers, which carries its own
        notification. Two messages for one move is noise.

        rindex, not index: swap_assignment has TWO `elif completed` blocks — an
        earlier one picking the in-app notification type, and the later Discord
        one. Anchoring on the first spans the call and passes for the wrong
        reason."""
        i = SWAP.rindex('elif dispatch_phase == "completed":')
        assert "_fire_crew_embed_update(" not in SWAP[i:]


class TestManualAssignmentAlsoReachesTheChannel:
    """ADR-288 D5, second path — found by the Dimension-8 audit pass.

    D5 was implemented against swap_assignment (drag a member between trucks).
    But manual_assignment is the OTHER way a member lands on a published truck
    (drag from the available pool), and it DM'd the individual while leaving
    the truck channel's posted crew embed stale — the identical defect D5
    exists to fix. The feature was half-applied until the audit asked "which
    other write paths create the data this depends on?".
    """

    def test_it_posts_a_correction_on_an_active_truck(self):
        assert "_fire_crew_embed_update(" in ASSIGN

    def test_it_targets_the_trucks_channel(self):
        i = ASSIGN.index("_fire_crew_embed_update(")
        assert "truck=truck," in ASSIGN[i : i + 400]

    def test_it_is_not_gated_on_the_employee_having_discord(self):
        """The DM above is gated on `employee.discord_id and not existing_conf`.
        The correction must not inherit either guard: a crew member the bot
        cannot DM is precisely the one the channel needs told about."""
        i = ASSIGN.index("_fire_crew_embed_update(")
        guard_line = ASSIGN[:i].rstrip().splitlines()[-1]
        assert 'if dispatch_phase == "active":' in guard_line
        assert "discord_id" not in guard_line
        assert "existing_conf" not in guard_line

    def test_completed_adds_do_not_get_one(self):
        """A completed-phase add grants channel access with announce=False and
        is handled by the transfer/grant path — not a correction."""
        i = ASSIGN.index('if dispatch_phase == "completed" and truck.discord_channel_id:')
        assert "_fire_crew_embed_update(" not in ASSIGN[i:]
