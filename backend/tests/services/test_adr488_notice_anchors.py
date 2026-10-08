"""A notice fires on the tenant's clock, or not at all (ADR-488 D3, D4, D6).

WHAT THIS REPLACES, AND WHY THE TIMEZONE IS THE WHOLE POINT
===========================================================

Three beat tasks notified people on a fixed SERVER hour:

    warn_before_mfa_deadline     16:30 server, NO tenant awareness at all
    remind_fuel_log_missing      17:00 + 18:30 server, tenant DATE only
    alert_finalization_deadline  09:05 server

So a Los Angeles employee was warned about their MFA deadline at 13:30 local,
and a tenant whose drivers return at 20:00 was reminded to file a fuel log three
hours before anyone could have filed one.

The tests below pin the arithmetic that fixes it, and the two properties that
make the fix safe rather than merely different: an unconfigured anchor SKIPS
(rather than guessing midnight), and a late sweep fires LATE rather than never
(rather than silently dropping the day).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models.notice import (
    CONFIG_BACKED_ANCHORS, Anchor, Condition, NoticeOrigin,
    TENANT_SELECTABLE_CONDITIONS,
)
from app.services.notices import (
    MAX_LATENESS, is_due_today, pass_number_due, resolve_anchor,
    tenant_notice_must_end,
)

LA = ZoneInfo("America/Los_Angeles")
NY = ZoneInfo("America/New_York")


def _notice(anchor, offset=0, at=None):
    return SimpleNamespace(id="n1", anchor=str(anchor), offset_minutes=offset, at_local=at)


def _cfg(**kw):
    base = dict(shift_start=time(6, 0), shift_end=time(20, 0),
                dispatch_confirmation_cutoff=time(9, 10))
    base.update(kw)
    return SimpleNamespace(**base)


def _sched(**kw):
    base = dict(id="s1", mode="daily", starts_on=date(2026, 1, 1), ends_on=None,
                weekday=None, fired_on=None, fired_count=0,
                max_fires_per_day=1, repeat_after_minutes=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestTheAnchorResolvesInTheTenantsZone:
    """The defect, stated as a test: the same wall-clock time is a different
    instant in two tenants, and the old tasks fired at one instant for both."""

    def test_the_same_local_hour_is_three_hours_apart(self):
        d = date(2026, 7, 15)
        n = _notice(Anchor.FIXED_LOCAL, at=time(16, 30))
        la = resolve_anchor(n, _cfg(), LA, d)
        ny = resolve_anchor(n, _cfg(), NY, d)
        assert (la - ny) == timedelta(hours=3), (
            "16:30 local must be a different UTC instant in LA and NY; firing "
            "both at one server hour is the MFA warning bug"
        )

    def test_shift_end_minus_fifteen(self):
        """A driver cannot file a fuel log before returning. 17:00 server was
        three hours early for a tenant whose drivers return at 20:00."""
        got = resolve_anchor(
            _notice(Anchor.SHIFT_END, offset=-15), _cfg(shift_end=time(20, 0)), NY,
            date(2026, 7, 15),
        )
        # 19:45 EDT == 23:45 UTC
        assert got == datetime(2026, 7, 15, 23, 45, tzinfo=timezone.utc)

    def test_the_cutoff_minus_five(self):
        """Five minutes: enough to act, late enough that the truck list is real."""
        got = resolve_anchor(
            _notice(Anchor.DISPATCH_CUTOFF, offset=-5),
            _cfg(dispatch_confirmation_cutoff=time(9, 10)), NY, date(2026, 7, 15),
        )
        assert got == datetime(2026, 7, 15, 13, 5, tzinfo=timezone.utc)

    def test_local_midnight_needs_no_config(self):
        got = resolve_anchor(_notice(Anchor.LOCAL_MIDNIGHT), None, LA, date(2026, 7, 15))
        assert got == datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)

    def test_the_anchor_value_is_the_config_column_name(self):
        """`getattr(cfg, anchor)` is how resolution works, so the enum VALUES
        must be column names rather than tidier labels."""
        cfg = _cfg()
        for a in CONFIG_BACKED_ANCHORS:
            assert hasattr(cfg, str(a)), f"{a} does not name a CompanyConfig column"

    def test_dst_is_not_a_relabel(self):
        """ADR-486's trap: attaching UTC to a naive Time RELABELS it. The same
        local time in January and July must differ by an hour in UTC."""
        n = _notice(Anchor.SHIFT_END)
        jan = resolve_anchor(n, _cfg(shift_end=time(20, 0)), NY, date(2026, 1, 15))
        jul = resolve_anchor(n, _cfg(shift_end=time(20, 0)), NY, date(2026, 7, 15))
        assert jan.hour != jul.hour, (
            "20:00 New York is 01:00 UTC in winter and 00:00 in summer; an "
            "identical UTC hour means the Time column was relabelled, not converted"
        )


class TestAnUnconfiguredAnchorSkipsRatherThanGuessing:
    """ADR-482's rule: a platform setting that never arrived must fail LOUDLY.

    ADR-485's own idiom falls back to `datetime.min.time()`, which is right for
    opening a campaign run and wrong here — a fuel-log reminder at 00:00 is
    noise delivered at the worst possible hour.
    """

    def test_a_null_column_returns_none(self):
        assert resolve_anchor(
            _notice(Anchor.SHIFT_END), _cfg(shift_end=None), NY, date(2026, 7, 15),
        ) is None

    def test_a_missing_config_row_returns_none(self):
        assert resolve_anchor(
            _notice(Anchor.SHIFT_END), None, NY, date(2026, 7, 15),
        ) is None

    def test_it_does_not_fall_back_to_midnight(self):
        """The specific wrong answer this avoids."""
        got = resolve_anchor(
            _notice(Anchor.SHIFT_END), _cfg(shift_end=None), NY, date(2026, 7, 15),
        )
        midnight = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)   # 00:00 EDT
        assert got != midnight, "an unconfigured anchor fell back to midnight"

    def test_a_fixed_local_with_no_time_is_a_bad_row_not_a_config_gap(self):
        """The CheckConstraint should prevent it, so reaching here means the
        constraint was bypassed — distinguished in the log rather than conflated
        with a tenant who has not configured something."""
        assert resolve_anchor(
            _notice(Anchor.FIXED_LOCAL, at=None), _cfg(), NY, date(2026, 7, 15),
        ) is None


class TestLateIsBetterThanNever:
    """A window test ("did it fire in the last 15 minutes") silently drops any
    notice whose window elapsed while the worker was down — ADR-487 D3's
    lost-`.delay()` failure in a new place."""

    FIRE = datetime(2026, 7, 16, 2, 45, tzinfo=timezone.utc)

    def test_not_yet_due(self):
        assert pass_number_due(_sched(), self.FIRE, self.FIRE - timedelta(minutes=5)) is None

    def test_due_the_moment_it_passes(self):
        assert pass_number_due(_sched(), self.FIRE, self.FIRE + timedelta(minutes=1)) == 1

    def test_still_due_an_hour_late(self):
        """The property a window test would break."""
        assert pass_number_due(_sched(), self.FIRE, self.FIRE + timedelta(hours=1)) == 1

    def test_abandoned_past_max_lateness(self):
        """"File your fuel log" at 02:00 because the worker was down since 18:00
        is worse than silence."""
        assert pass_number_due(
            _sched(), self.FIRE, self.FIRE + MAX_LATENESS + timedelta(minutes=1),
        ) is None

    def test_already_fired_does_not_refire(self):
        """Idempotency is what makes the interval safe to change: without it,
        halving the interval doubles the messages."""
        assert pass_number_due(_sched(fired_count=1), self.FIRE,
                               self.FIRE + timedelta(minutes=20)) is None


class TestTheSecondPass:
    """`remind_fuel_log_missing` fires at 17:00 AND 18:30 on purpose — "a second
    pass re-notifies any still-missing drivers, this handles late returns". A
    first draft of ADR-488 had only `fired_on` and would have dropped it."""

    FIRE = datetime(2026, 7, 16, 2, 45, tzinfo=timezone.utc)
    TWO = dict(max_fires_per_day=2, repeat_after_minutes=90)

    def test_the_first_pass_fires_at_the_anchor(self):
        assert pass_number_due(_sched(**self.TWO), self.FIRE,
                               self.FIRE + timedelta(minutes=1)) == 1

    def test_the_second_waits_for_the_interval(self):
        s = _sched(fired_count=1, **self.TWO)
        assert pass_number_due(s, self.FIRE, self.FIRE + timedelta(minutes=5)) is None
        assert pass_number_due(s, self.FIRE, self.FIRE + timedelta(minutes=95)) == 2

    def test_there_is_no_third(self):
        assert pass_number_due(_sched(fired_count=2, **self.TWO), self.FIRE,
                               self.FIRE + timedelta(hours=3)) is None

    def test_a_single_pass_notice_fires_once(self):
        assert pass_number_due(_sched(fired_count=1), self.FIRE,
                               self.FIRE + timedelta(hours=1)) is None


class TestRecurrence:
    """The four modes are `CampaignSchedule`'s, deliberately — ADR-488 D2 reuses
    that vocabulary rather than inventing a second scheduler."""

    def test_daily(self):
        assert is_due_today(_sched(mode="daily"), date(2026, 7, 15))

    def test_before_the_start_date(self):
        assert not is_due_today(_sched(starts_on=date(2026, 8, 1)), date(2026, 7, 15))

    def test_after_the_end_date(self):
        assert not is_due_today(
            _sched(ends_on=date(2026, 7, 1)), date(2026, 7, 15))

    def test_a_null_end_date_never_expires(self):
        """A platform notice anchored to shift_end should not expire: the
        condition it reports on recurs indefinitely (ADR-488 D11)."""
        assert is_due_today(_sched(ends_on=None), date(2099, 1, 1))

    def test_weekly_fixed_only_on_its_weekday(self):
        wed = date(2026, 7, 15)
        assert wed.weekday() == 2
        assert is_due_today(_sched(mode="weekly_fixed", weekday=2), wed)
        assert not is_due_today(_sched(mode="weekly_fixed", weekday=3), wed)

    def test_weekly_random_is_stable_within_a_week(self):
        """NOT random per call: that would make a notice fire on a different day
        every time the sweep ran. Seeded on the schedule id and the ISO week."""
        s = _sched(mode="weekly_random")
        week = [date(2026, 7, 13) + timedelta(days=i) for i in range(7)]
        hits = [d for d in week if is_due_today(s, d)]
        assert len(hits) == 1, f"a weekly notice fired on {len(hits)} days"
        # and the answer does not change between calls
        assert is_due_today(s, hits[0])

    def test_an_unknown_mode_does_not_fire(self):
        assert not is_due_today(_sched(mode="hourly"), date(2026, 7, 15))


class TestTheTenantMustEndRule:
    """ADR-488 D11. A cross-table CHECK is not portable, so this rule lives in
    the service layer — which means it needs a test, or it is a comment."""

    def test_a_tenant_notice_without_an_end_violates(self):
        n = SimpleNamespace(origin=NoticeOrigin.TENANT.value)
        assert tenant_notice_must_end(n, _sched(ends_on=None)) is True

    def test_a_tenant_notice_with_an_end_is_fine(self):
        n = SimpleNamespace(origin=NoticeOrigin.TENANT.value)
        assert tenant_notice_must_end(n, _sched(ends_on=date(2026, 12, 1))) is False

    def test_a_platform_notice_may_be_endless(self):
        n = SimpleNamespace(origin=NoticeOrigin.PLATFORM.value)
        assert tenant_notice_must_end(n, _sched(ends_on=None)) is False


class TestTheConditionEnumIsClosed:
    def test_a_tenant_may_only_select_always(self):
        """A tenant-expressible condition is a query language, and a query
        language against tenant data reached from a scheduler is a surface this
        system has no reason to open (ADR-488 D5)."""
        assert TENANT_SELECTABLE_CONDITIONS == {Condition.ALWAYS}

    def test_the_timecard_scan_is_not_a_condition(self):
        """ADR-488 D5a: `detect_timecard_mismatches` db.add()s rows — it IS the
        scan, not a reminder that one happened. As a notice, an unconfigured
        anchor would silently skip the DETECTION rather than a message."""
        assert not any("timecard" in c.value for c in Condition), (
            "the timecard scan became a condition; if skipping a notice would "
            "skip WORK rather than a message, it is a task"
        )
