"""ADR-115 dim 8 for ADR-264 — the two training tracks must not pool.

FOUND BY THE AUDIT, NOT BY A FAILING TEST
-----------------------------------------
A driver trainee has TrainingRecord rows and a role that is not "trainee". Every
walker-shaped aggregate that keys on either fact silently absorbs them.

`_graduation_pct` defines graduated as "has training records but role is no
longer 'trainee'". A driver trainee satisfied both halves from the day their
first record was written, so they counted as ALREADY GRADUATED — inflating the
walker graduation rate while also sitting in the denominator.

`analytics.py` was safe for a reason worth recording: it filters
`trainer_id.isnot(None)`, and the driver track writes `driver_trainer_id`
instead. Splitting that column (operator, 2026-08-22) is what kept a whole
class of walker aggregates correct by construction.
"""
import inspect

from app.services import dashboard_summaries as ds


class TestGraduationRateIsWalkerOnly:
    SRC = inspect.getsource(ds._graduation_pct)

    def test_driver_trainees_are_excluded(self):
        assert 'Employee.role != "driver_trainee"' in self.SRC

    def test_they_leave_the_denominator_too(self):
        """Excluding them only from the numerator would deflate the rate
        instead of inflating it — still wrong, just the other way."""
        assert "len(walker_track_ids)" in self.SRC
        assert "len(trainee_ids)" not in self.SRC.split("walker_track_ids")[-1]

    def test_the_walker_graduate_is_still_counted(self):
        """A walker trainee who graduated is now a `walker` — the exact case
        this measures. Filtering RECORDS by track would drop them."""
        assert 'Employee.role != "trainee"' in self.SRC


class TestTheColumnSplitProtectsWalkerAggregates:
    def test_analytics_open_records_excludes_the_driver_track(self):
        """Not by an explicit filter — by `trainer_id.isnot(None)`, which the
        driver track never sets. If the tracks had shared one column this
        would have needed a filter nobody would have thought to add."""
        from app.routers import analytics

        src = inspect.getsource(analytics)
        i = src.index("TrainingRecord.submitted_at.is_(None)")
        assert "TrainingRecord.trainer_id.isnot(None)" in src[i : i + 260]

    def test_the_driver_track_never_writes_trainer_id(self):
        from app.services.training_injection import _inject_driver_track

        src = inspect.getsource(_inject_driver_track)
        i = src.index("record = TrainingRecord(")
        ctor = src[i : src.index(")", src.index("company_id=company_id", i))]
        assert "driver_trainer_id=" in ctor
        assert "trainer_id=" not in ctor.replace("driver_trainer_id=", "")
