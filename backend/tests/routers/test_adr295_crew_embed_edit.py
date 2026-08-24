"""ADR-295 — the crew embed is EDITED in place, with a chat notice.

THE FAILURE THIS REMOVES
------------------------
ADR-288 D5 posted a *correction* embed beside a stale roster, because the bot
did not keep the message id of the original. That left the channel's
authoritative crew list wrong: a driver scrolling back read a stale roster and
had to reconstruct the truth from a later message.

ADR-288 claimed the send was fire-and-forget (`asyncio.create_task`) and so the
Message was unrecoverable. That was the WRONG endpoint — `/internal/post-embed`,
used by anchor points. The crew embeds are sent from cogs/dispatch.py and both
sites already `await`, returning a Message that was simply discarded. Only
persistence and the edit path were missing.

dispatch.py is proprietary; CI copies it in before pytest, so there is
deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch
from app.models.truck_assignment import TruckAssignment


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


UPDATE = _code_only(dispatch._fire_crew_embed_update)
RECORD = _code_only(dispatch.record_crew_embed_message)
ASSIGN = _code_only(dispatch.manual_assignment)
SWAP   = _code_only(dispatch.swap_assignment)
REMOVE = _code_only(dispatch.remove_assignment)


class TestMessageIdIsPersisted:
    """D1 — without a stored id there is nothing to edit."""

    def test_the_column_exists_and_is_a_bigint(self):
        col = TruckAssignment.__table__.c.crew_embed_message_id
        assert str(col.type) in ("BIGINT", "BigInteger")

    def test_it_is_nullable(self):
        """Must stay nullable: rows predating the column have no embed, a failed
        channel post has none, and D4 CLEARS it to NULL when the message is
        found deleted. A NOT NULL default makes 'no embed' unrepresentable."""
        assert TruckAssignment.__table__.c.crew_embed_message_id.nullable is True


class TestRecordEndpoint:
    """D2 — the bot reports the id back."""

    def test_it_is_company_scoped(self):
        """Dimension 1: the lookup must not resolve another tenant's truck-day."""
        assert "TruckAssignment.company_id == caller.company_id" in RECORD

    def test_it_writes_an_audit_row_between_flush_and_commit(self):
        i_flush = RECORD.index("db.flush()")
        i_audit = RECORD.index("write_audit(")
        i_commit = RECORD.index("db.commit()")
        assert i_flush < i_audit < i_commit

    def test_zero_clears_the_column_to_null(self):
        """D4's sentinel. `or None` is what turns 0 into NULL — without it the
        column stores 0, and the next change fetches message id 0 forever."""
        assert "body.message_id or None" in RECORD

    def test_the_schema_accepts_the_clear_sentinel(self):
        f = dispatch.CrewEmbedMessageRequest.model_fields["message_id"]
        meta = {type(m).__name__: m for m in f.metadata}
        assert meta["Ge"].ge == 0, "ge=1 would 422 the D4 clear"

    def test_the_schema_forbids_extra_keys(self):
        """Dimension 9 — a request model at the trust boundary."""
        assert dispatch.CrewEmbedMessageRequest.model_config.get("extra") == "forbid"

    def test_the_schema_bounds_the_upper_end(self):
        f = dispatch.CrewEmbedMessageRequest.model_fields["message_id"]
        meta = {type(m).__name__: m for m in f.metadata}
        assert meta["Le"].le == 9223372036854775807, "must not exceed signed BIGINT"


class TestEditReplacesCorrection:
    """D3 — edit the real message, then say it changed."""

    def test_the_correction_helper_is_gone(self):
        assert not hasattr(dispatch, "_fire_crew_correction")

    def test_it_sends_the_roster_as_it_now_stands(self):
        """The bot rebuilds the embed from truth rather than patching text, so
        the payload must carry the current crew, not just the delta."""
        assert '"crew": crew_payload' in UPDATE

    def test_it_sends_the_stored_message_id(self):
        assert '"message_id": truck_assignment.crew_embed_message_id' in UPDATE

    def test_it_names_the_change_so_the_notice_can_say_what_happened(self):
        assert '"change": {"verb": verb, "employee_name": employee_name}' in UPDATE

    def test_the_roster_query_is_company_scoped(self):
        assert "Employee.company_id == company_id" in UPDATE

    def test_a_truck_with_no_channel_is_a_no_op(self):
        assert "if not truck.discord_channel_id:" in UPDATE
        i = UPDATE.index("if not truck.discord_channel_id:")
        assert "return" in UPDATE[i : i + 60]

    def test_the_roster_is_not_queried_inside_the_thread(self):
        """The background thread must not touch the request's Session — it is
        closed by the time the thread runs. Only the HTTP POST may be deferred.

        Parsed, not string-compared. A source-order assertion
        (`index("db.query") < index("threading.Thread")`) passes even when the
        query has been moved INSIDE _run(), because _run is *defined* above the
        Thread(...) line — verified by planting exactly that and watching the
        ordering test stay green."""
        import ast
        tree = ast.parse(inspect.getsource(dispatch._fire_crew_embed_update).lstrip())
        run = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_run"
        )
        calls = [
            n.func.attr for n in ast.walk(run)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        assert "query" not in calls, "the roster query must not run on the thread"

    def test_it_is_fire_and_forget(self):
        assert "threading.Thread(" in UPDATE and "daemon=True" in UPDATE

    def test_failures_are_logged_not_raised(self):
        assert "logger.warning(" in UPDATE
        assert "raise" not in UPDATE


class TestEveryCrewChangePathEdits:
    """All three write paths onto a published truck, not just the one under
    development. This is the Dimension-8 question that caught D5 being
    half-applied in ADR-288."""

    def test_manual_assignment_edits_on_add(self):
        assert "_fire_crew_embed_update(" in ASSIGN
        i = ASSIGN.index("_fire_crew_embed_update(")
        assert 'verb="added"' in ASSIGN[i : i + 400]

    def test_swap_assignment_edits_on_add(self):
        assert "_fire_crew_embed_update(" in SWAP
        i = SWAP.index("_fire_crew_embed_update(")
        assert 'verb="added"' in SWAP[i : i + 400]

    def test_removal_edits_too(self):
        """D5 — ADR-288 covered additions only, because a correction naming a
        removed person reads as a reprimand. An edit has no such problem."""
        assert "_fire_crew_embed_update(" in REMOVE
        i = REMOVE.index("_fire_crew_embed_update(")
        assert 'verb="removed"' in REMOVE[i : i + 400]

    def test_swap_passes_the_destination_truck_not_the_source(self):
        i = SWAP.index("_fire_crew_embed_update(")
        block = SWAP[i : i + 400]
        assert "truck=destination_truck" in block
        assert "truck_assignment=destination_assignment" in block

    def test_removal_passes_the_source_truck(self):
        i = REMOVE.index("_fire_crew_embed_update(")
        assert "truck=source_truck" in REMOVE[i : i + 400]


class TestRemovalPhaseIsPerTruck:
    """The THIRD copy of the day-level phase scan, after manual_assignment and
    swap_assignment. It revoked a removed employee's channel access based on
    some OTHER truck having been finalized — and skipped the revoke when this
    truck was finalized but no other was."""

    def test_phase_reads_this_trucks_own_status(self):
        assert 'remove_phase = (truck_assignment.status or "planned")' in REMOVE

    def test_the_date_wide_scan_is_gone(self):
        assert "date_statuses" not in REMOVE

    def test_no_date_wide_scan_feeds_the_phase(self):
        """Scoped to the phase derivation, not the whole handler: the member
        lookup legitimately filters `TruckAssignment.date == date` to find WHICH
        member to remove. What must not come back is a second query whose result
        sets remove_phase."""
        i = REMOVE.index("remove_phase =")
        window = REMOVE[max(0, i - 600) : i]
        assert "db.query(TruckAssignment)" not in window

    def test_the_source_truck_lookup_is_company_scoped(self):
        """Dimension 1 — a bare `Truck.id ==` lookup resolves another tenant's
        truck if an id ever reaches this path."""
        i = REMOVE.index("source_truck = db.query(Truck)")
        assert "Truck.company_id == caller.company_id" in REMOVE[i : i + 300]
