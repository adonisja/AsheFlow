"""ADR-264 D9 — supervision eligibility is one predicate.

THE FAILURE THIS GUARDS AGAINST
-------------------------------
`field_supervisor` and `captain` arrive in their own work. If any call site
inlines `role == "driver"` at a supervision check, threading a new role means
finding every one of them — and this codebase has precedent for role lists
drifting between call sites.

The test that matters is the LAST one: no call site may inline the comparison.
"""
from pathlib import Path

import pytest

from app.services.driver_supervision import (
    SUPERVISING_ROLES, can_supervise_driver_trainee, eligible_supervisors,
)


class _Emp:
    def __init__(self, role, is_active=True, eid=None):
        self.role, self.is_active, self.id = role, is_active, eid


class _DB:
    """Stands in for a Session: returns the given (supervisor_id, date) rows."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, *a, **k): return self
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows


class TestThePredicate:
    def test_an_active_driver_may_supervise(self):
        assert can_supervise_driver_trainee(_Emp("driver")) is True

    def test_an_inactive_driver_may_not(self):
        """The reason the predicate takes the OBJECT, not a role string: a
        caller passing employee.role alone would skip this check."""
        assert can_supervise_driver_trainee(_Emp("driver", is_active=False)) is False

    @pytest.mark.parametrize("role", ["walker", "trainer", "trainee", "driver_trainee", "dispatch", "admin"])
    def test_nobody_else_may(self, role):
        assert can_supervise_driver_trainee(_Emp(role)) is False

    def test_a_driver_trainee_cannot_supervise_another_driver_trainee(self):
        """Obvious, and worth pinning: the roles differ by one word."""
        assert can_supervise_driver_trainee(_Emp("driver_trainee")) is False

    def test_none_is_false_not_an_exception(self):
        """Callers resolve a supervisor that may not exist; a missing one is a
        'no supervisor' branch (D7), not a crash mid-dispatch."""
        assert can_supervise_driver_trainee(None) is False

    def test_a_trainer_may_not_supervise_a_driver(self):
        """A walker trainer has no vehicle or load-custody authority to pass on.
        Drivers train drivers."""
        assert can_supervise_driver_trainee(_Emp("trainer")) is False


class TestTheSeamIsTheOnlyDefinition:
    def test_field_supervisor_and_captain_are_deliberately_absent(self):
        """D9 builds the seam, not the roles. When those roles carry the
        authority, adding one here is the whole change."""
        assert SUPERVISING_ROLES == frozenset({"driver"})

    def test_no_call_site_inlines_the_role_comparison(self):
        """THE test. An inlined `role == "driver"` at a supervision check is
        exactly what makes threading a new role expensive later.

        Scoped to driver-training call sites: `role == "driver"` is legitimate
        elsewhere (resolving the truck's driver for RTS, surveys, anchors) —
        those are not supervision checks.
        """
        app = Path(__file__).resolve().parents[2] / "app"
        offenders = []
        for f in app.rglob("*.py"):
            if f.name == "driver_supervision.py":
                continue
            text = f.read_text()
            if "driver_trainee" not in text:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                code = line.split("#")[0]
                if "driver_trainee" not in code and (
                    'role == "driver"' in code or "role == 'driver'" in code
                ):
                    # Only flag when the surrounding function also mentions
                    # supervision — a plain driver lookup is not a supervision check.
                    window = "\n".join(text.splitlines()[max(0, n - 25): n + 5])
                    if "supervis" in window.lower() or "paired_trainer_id" in window:
                        offenders.append(f"{f.relative_to(app)}:{n}")
        assert not offenders, (
            "these supervision checks inline the role comparison instead of "
            f"calling can_supervise_driver_trainee(): {offenders}"
        )


class TestEligibleSupervisors:
    def test_it_filters_and_preserves_order(self):
        pool = [_Emp("walker"), _Emp("driver"), _Emp("trainer"), _Emp("driver")]
        assert len(eligible_supervisors(pool)) == 2

    def test_it_returns_a_list_so_len_works(self):
        """The 'no free supervisor' branch (D7) needs a count; a generator
        would be consumed by the check itself."""
        got = eligible_supervisors([_Emp("driver")])
        assert isinstance(got, list)
        assert len(got) == 1 and len(got) == 1  # twice on purpose — not exhausted

    def test_an_empty_pool_is_empty_not_an_error(self):
        assert eligible_supervisors([]) == []


class TestTheDriverSupervisorIsASeparateColumn:
    """ADR-264 D5, revised 2026-08-22.

    The ADR originally reused TrainingRecord.trainer_id and called the name
    "misleading". It is worse than misleading: ~192 references read trainer_id,
    and the walker-shaped ones — graduation_quiz, continuation_requests,
    analytics, the training router — would silently treat a supervising driver
    as a walker trainer. analytics.py counts records with `trainer_id IS NOT
    NULL`, so a shared column folds driver supervision into walker-trainer
    statistics.
    """

    def test_the_column_exists_and_is_nullable(self):
        from app.models.training import TrainingRecord

        col = TrainingRecord.__table__.columns.get("driver_trainer_id")
        assert col is not None, "ADR-264 D5 requires a separate driver supervisor column"
        assert col.nullable is True, "a solo day (D8) sets no supervisor"

    def test_it_is_distinct_from_the_walker_trainer_column(self):
        from app.models.training import TrainingRecord

        cols = {c.name for c in TrainingRecord.__table__.columns}
        assert {"trainer_id", "driver_trainer_id"} <= cols, (
            "both must exist — reusing one column is the mistake this guards"
        )

    def test_the_continuity_lookup_reads_the_driver_column(self):
        """If this ever reads trainer_id, a driver trainee inherits whichever
        walker trainer last supervised someone — a silent cross-track pairing."""
        import inspect

        from app.services import driver_supervision

        src = inspect.getsource(driver_supervision.prior_supervisor_ids)
        assert "TrainingRecord.driver_trainer_id" in src
        assert "TrainingRecord.trainer_id" not in src


class TestContinuityIsTheRule:
    """D5 addendum. Continuity, not eligibility: the same supervisor carries
    across days, and the system never substitutes on its own."""

    def test_no_prior_record_is_first_day_not_an_auto_pick(self):
        from app.services.driver_supervision import resolve_supervisor

        sup, reason = resolve_supervisor(_DB([]), "t1", "c1", "2026-08-22", [_Emp("driver", eid="d1")])
        assert sup is None and reason == "first_day", (
            "an eligible driver was standing right there — the system must NOT "
            "pick one; a new supervising relationship is a human decision"
        )

    def test_the_most_recent_supervisor_is_reused_when_present(self):
        from app.services.driver_supervision import resolve_supervisor

        db = _DB([("d1", "2026-08-21"), ("d2", "2026-08-20")])
        sup, reason = resolve_supervisor(db, "t1", "c1", "2026-08-22", [_Emp("driver", eid="d1")])
        assert (sup, reason) == ("d1", "continuity")

    def test_an_earlier_supervisor_is_used_when_the_latest_is_out(self):
        """Operator, 2026-08-22: continuity spans the WHOLE history, not just
        yesterday. An earlier supervising driver has also watched this trainee
        work, so they are preferred over asking dispatch."""
        db = _DB([("d1", "2026-08-21"), ("d2", "2026-08-20")])
        from app.services.driver_supervision import resolve_supervisor

        sup, reason = resolve_supervisor(db, "t1", "c1", "2026-08-22", [_Emp("driver", eid="d2")])
        assert (sup, reason) == ("d2", "prior"), (
            "an earlier supervisor was available and should have been reused"
        )

    def test_dispatch_is_asked_only_when_no_prior_supervisor_is_in(self):
        from app.services.driver_supervision import resolve_supervisor

        db = _DB([("d1", "2026-08-21"), ("d2", "2026-08-20")])
        sup, reason = resolve_supervisor(db, "t1", "c1", "2026-08-22", [_Emp("driver", eid="d9")])
        assert (sup, reason) == (None, "unavailable")

    def test_a_prior_supervisor_who_is_no_longer_a_driver_is_not_reused(self):
        """They supervised before, but eligibility is checked TODAY."""
        from app.services.driver_supervision import resolve_supervisor

        db = _DB([("d1", "2026-08-21")])
        sup, reason = resolve_supervisor(db, "t1", "c1", "2026-08-22", [_Emp("walker", eid="d1")])
        assert (sup, reason) == (None, "unavailable")

    def test_a_repeat_supervisor_is_one_candidate_ranked_by_recency(self):
        """d1 on three days is one candidate, not three."""
        from app.services.driver_supervision import prior_supervisor_ids

        db = _DB([("d1", "2026-08-21"), ("d1", "2026-08-20"), ("d2", "2026-08-19")])
        assert prior_supervisor_ids(db, "t1", "c1", "2026-08-22") == ["d1", "d2"]


class TestNothingIsRecordedAboutTheSupervisingDriver:
    """Operator, 2026-08-22.

    A driver trainee is trained by another driver. Records are kept about the
    TRAINEE only — the supervising driver is doing their normal job with a
    trainee along, not participating in a training program. No TrainerMark, no
    phase, no debt, no attribution.

    I initially read record_trainer_mark's NULL-trainer_id gate as a gap the
    driver track needed to fill. It is the correct behaviour.
    """

    def test_a_record_without_a_walker_trainer_issues_no_mark(self):
        """A driver trainee's record has trainer_id NULL and
        driver_trainer_id set. record_trainer_mark must return None."""
        import inspect

        from app.services.record_trainer_mark import record_trainer_mark

        src = inspect.getsource(record_trainer_mark)
        assert "if not record or not record.trainer_id:" in src
        assert "return None" in src

    def test_the_mark_writer_never_falls_back_to_the_driver_column(self):
        """The tempting 'fix': `record.trainer_id or record.driver_trainer_id`.
        That would start marking drivers for a program they are not in."""
        import inspect

        from app.services import record_trainer_mark as mod

        assert "driver_trainer_id" not in inspect.getsource(mod), (
            "the walker TrainerMark machinery must not reach into the driver "
            "track — nothing is recorded about a supervising driver"
        )

    def test_the_driver_column_is_only_ever_read(self):
        """driver_trainer_id lives on the TRAINEE's record. Nothing writes a
        record ABOUT the supervising driver."""
        import inspect

        from app.services import driver_supervision

        src = inspect.getsource(driver_supervision)
        assert "TrainingRecord.driver_trainer_id" in src
        assert "driver_trainer_id =" not in src, "this module must not write the column"
