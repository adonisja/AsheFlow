"""ADR-198 — attendance reference floor rule + status derivation.

Pure-logic tests of _attendance_reference (floor: max(shift_start, AP-established))
and _derive_status (early/present/late/ncns vs the reference), including the two
edge cases that motivated it: an EARLY driver (floored) and a LATE driver (raises).
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.routers.roll_call import (
    _attendance_reference,
    _derive_status,
    DEFAULT_LATE_WINDOW,
    DEFAULT_NCNS_CUTOFF,
)

TZ = ZoneInfo("America/New_York")
DAY = datetime(2026, 7, 12).date()
SHIFT = time(11, 0)   # 11:00 scheduled start


def _dt(h, m):
    return datetime(2026, 7, 12, h, m, tzinfo=TZ)


class TestAttendanceReference:
    def test_no_shift_start_returns_none(self):
        assert _attendance_reference(None, _dt(10, 0), TZ, DAY) is None

    def test_no_ap_falls_back_to_floor(self):
        # AP never established → reference is the shift_start floor.
        ref = _attendance_reference(SHIFT, None, TZ, DAY)
        assert ref == datetime.combine(DAY, SHIFT, tzinfo=TZ)

    def test_early_driver_is_floored_to_shift_start(self):
        # Driver established AP at 10:00 (before 11:00 shift) → floored to 11:00.
        ref = _attendance_reference(SHIFT, _dt(10, 0), TZ, DAY)
        assert ref == datetime.combine(DAY, SHIFT, tzinfo=TZ)

    def test_late_driver_raises_reference(self):
        # Driver established AP at 12:00 (after 11:00 shift) → reference rises to 12:00.
        ref = _attendance_reference(SHIFT, _dt(12, 0), TZ, DAY)
        assert ref == _dt(12, 0)


class TestDeriveStatus:
    def test_none_reference_is_present(self):
        assert _derive_status(None, None, _dt(13, 0)) == "present"

    def test_before_reference_is_early(self):
        assert _derive_status(_dt(11, 0), 20, _dt(10, 55)) == "early"

    def test_within_late_window_is_present(self):
        # 11:15, window 20 → present
        assert _derive_status(_dt(11, 0), 20, _dt(11, 15)) == "present"

    def test_past_window_is_late(self):
        # 11:40, window 20, ncns cutoff 60 → late
        assert _derive_status(_dt(11, 0), 20, _dt(11, 40)) == "late"

    def test_past_ncns_cutoff_is_ncns(self):
        # 12:30 vs 11:00 ref = 90 min > 60 cutoff → ncns
        assert _derive_status(_dt(11, 0), 20, _dt(12, 30), ncns_cutoff_minutes=60) == "ncns"

    def test_late_driver_keeps_crew_on_time(self):
        # The motivating case: driver late (AP at 12:00), crew arrives 12:10.
        # Against a FIXED 11:00 shift they'd be 70 min late (ncns). Against the
        # AP-anchored reference (12:00) they're 10 min → present.
        ref = _attendance_reference(SHIFT, _dt(12, 0), TZ, DAY)
        assert _derive_status(ref, 20, _dt(12, 10)) == "present"

    def test_early_driver_does_not_make_normal_crew_late(self):
        # Driver early (AP 10:00), floored to 11:00. Crew arrives 11:10 → present
        # (not judged against the 10:00 AP).
        ref = _attendance_reference(SHIFT, _dt(10, 0), TZ, DAY)
        assert _derive_status(ref, 20, _dt(11, 10)) == "present"

    def test_defaults(self):
        assert DEFAULT_LATE_WINDOW == 20
        assert DEFAULT_NCNS_CUTOFF == 60
