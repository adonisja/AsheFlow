"""Package exception attribution — executor vs recorder (ADR-244).

rts_packages.walker_id was stamped as caller.id while the code computed
route.executor_id for its permission check and then discarded it. Elevated roles
(trainer, driver, dispatch, management) may submit on a walker's behalf, so those
rows recorded the SUBMITTER and lost the walker whose route it was.

That breaks two things: accountability (who marked it) and the improvement
baseline (whose record it counts against). Since the row also carries the cause,
procedure and outcome, correct attribution is what makes it a coaching signal
rather than a bare count.
"""
import inspect

import app.routers.rts as rts
from app.models.delivery_stop import DeliveryStop
from app.models.rts import RTSPackage, MissingPackage, DamagedPackage


class TestSchema:
    def test_route_bound_tables_have_both_actors(self):
        for M in (RTSPackage, MissingPackage):
            cols = {c.key for c in M.__table__.columns}
            assert "walker_id" in cols, f"{M.__name__} lost its executor column"
            assert "recorded_by" in cols, f"{M.__name__} has no recorder column"
            assert "recorded_by_name" in cols

    def test_damaged_packages_deliberately_has_no_executor(self):
        """Damage is usually found at station sort, before a route exists — there
        is no executor to attribute, and inventing one would be worse than
        leaving it absent (ADR-244)."""
        cols = {c.key for c in DamagedPackage.__table__.columns}
        assert "reported_by" in cols
        assert "walker_id" not in cols
        assert "recorded_by" not in cols

    def test_recorded_by_is_nullable(self):
        """Rows predating the migration cannot distinguish the two actors; null
        is an honest 'unknown' rather than a fabricated attribution."""
        for M in (RTSPackage, MissingPackage):
            assert M.__table__.columns["recorded_by"].nullable


class TestExecutorResolution:
    def test_helper_exists_and_takes_db(self):
        """It must query for the executor's name, so it needs a session — the
        first version of this change called it from a helper with no db in
        scope, which would have been a runtime NameError."""
        sig = inspect.signature(rts._executor_identity)
        assert list(sig.parameters) == ["db", "route", "caller"]

    def test_falls_back_to_caller_when_route_has_no_executor(self):
        """Pre-ADR-212 routes have no executor participant. Falling back to the
        caller keeps the old behaviour rather than writing null."""
        class _Route:
            executor_id = None

        class _Caller:
            id = "caller-uuid"
            name = "Caller Name"
            company_id = "co"

        got = rts._executor_identity(None, _Route(), _Caller())
        assert got == ("caller-uuid", "Caller Name")

    def test_self_submit_short_circuits_without_a_query(self):
        """When the executor IS the caller the helper must not hit the database —
        passing db=None here proves it never dereferences the session."""
        class _Route:
            executor_id = "same-uuid"

        class _Caller:
            id = "same-uuid"
            name = "Walker Name"
            company_id = "co"

        assert rts._executor_identity(None, _Route(), _Caller()) == ("same-uuid", "Walker Name")


class TestWritePaths:
    def _src(self, fn):
        return inspect.getsource(fn)

    def test_rts_create_stamps_executor_and_recorder_separately(self):
        src = self._src(rts.record_rts_package)
        assert "walker_id           = _exec_identity[0]" in src, \
            "walker_id must be the route's executor, not the caller"
        assert "recorded_by         = caller.id" in src, \
            "recorded_by must be the submitter"

    def test_missing_create_stamps_executor_and_recorder_separately(self):
        src = self._src(rts.report_missing_package)
        assert "walker_id           = _exec_identity[0]" in src
        assert "recorded_by         = caller.id" in src

    def test_neither_write_path_stamps_walker_id_from_caller(self):
        """The original defect, pinned directly."""
        for fn in (rts.record_rts_package, rts.report_missing_package):
            src = self._src(fn)
            assert "walker_id           = caller.id" not in src, \
                f"{fn.__name__} reintroduced the executor/recorder conflation"


class TestDeliveryStopAttribution:
    """ADR-244 amendment. delivery_stops had the same conflation, and it matters
    more: walker_id feeds get_my_performance (a driver's own stats on mobile),
    cross_check_scorecard's our_delivered (the figure we appeal Amazon with), and
    the management top-walker rankings.

    Two real workflows produce a mismatch — a trainer completing a trainee's stop
    during supervision, and a walker covering another's stop in an emergency.
    """

    def test_delivery_stop_has_both_actors(self):
        cols = {c.key for c in DeliveryStop.__table__.columns}
        assert "walker_id" in cols
        assert "recorded_by" in cols
        assert "recorded_by_name" in cols

    def test_recorded_by_is_nullable(self):
        """Stops predating the migration cannot distinguish the two actors."""
        assert DeliveryStop.__table__.columns["recorded_by"].nullable

    def test_complete_stamps_executor_and_completer_separately(self):
        src = inspect.getsource(rts.complete_delivery_stop)
        assert "stop.walker_id          = _stop_exec[0]" in src, \
            "walker_id must be the route's executor, not the caller"
        assert "stop.recorded_by        = caller.id" in src, \
            "recorded_by must be whoever completed the stop"

    def test_start_stamps_executor_and_starter_separately(self):
        src = inspect.getsource(rts.start_delivery_stop)
        assert "stop.walker_id   = _stop_exec[0]" in src
        assert "stop.recorded_by      = caller.id" in src

    def test_neither_stop_path_stamps_walker_id_from_caller(self):
        """The defect, pinned directly in both handlers."""
        for fn in (rts.complete_delivery_stop, rts.start_delivery_stop):
            src = inspect.getsource(fn)
            assert "stop.walker_id          = caller.id" not in src, \
                f"{fn.__name__} reintroduced the conflation"
            assert "stop.walker_id  = caller.id" not in src, \
                f"{fn.__name__} reintroduced the conflation"
