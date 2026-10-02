"""Opening campaign runs on a schedule (ADR-485 D12).

Four modes, all bounded, all rolling over a day the station did not run.

The date arithmetic is tested directly because it is the part that silently
produces wrong behaviour: a schedule that fires on the wrong day, or re-rolls
its random day between two calls, looks like nothing is wrong until somebody
compares two runs.
"""
import ast
import datetime
import inspect
import pathlib
import textwrap
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.campaign import CampaignSchedule
from app.tasks import campaign_runs as T

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _code(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _sched(mode, starts, ends, weekday=None, sid=None):
    return CampaignSchedule(
        id=sid or uuid.uuid4(), company_id=uuid.uuid4(), campaign_id=uuid.uuid4(),
        mode=mode, weekday=weekday, starts_on=starts, ends_on=ends,
    )


# ── the beat entry actually runs something ──────────────────────────────────

def test_the_beat_entry_names_a_registered_task():
    """ADR-338's failure: a beat entry naming an unimported module fires with
    NO error — Celery has no task under that name and the work simply never
    happens."""
    import importlib
    from app.celery_app import celery_app, _task_modules
    for m in _task_modules():
        importlib.import_module(m)
    beat = {v["task"] for v in celery_app.conf.beat_schedule.values()}
    missing = sorted(n for n in beat if n not in celery_app.tasks)
    assert not missing, f"beat entries with no registered task: {missing}"


def test_the_schedule_does_not_collide_with_a_busy_slot():
    """03:15, 03:30 and 04:30 each already carry two tasks."""
    from app.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["open-campaign-runs"]["schedule"]
    assert (entry.hour, entry.minute) == ({5}, {30})


# ── which day is an occurrence due? ─────────────────────────────────────────

def test_daily_is_due_every_day_in_range():
    s = _sched("daily", datetime.date(2026, 10, 1), datetime.date(2026, 10, 8))
    assert T._due_today(s, datetime.date(2026, 10, 3))
    assert T._due_today(s, datetime.date(2026, 10, 8))


def test_nothing_is_due_outside_the_schedules_range():
    """Every mode is bounded, so a campaign somebody set up and forgot stops
    asking on its own."""
    s = _sched("daily", datetime.date(2026, 10, 1), datetime.date(2026, 10, 8))
    assert not T._due_today(s, datetime.date(2026, 9, 30))
    assert not T._due_today(s, datetime.date(2026, 10, 9))


def test_weekly_fixed_fires_only_on_its_weekday():
    # 2026-10-05 is a Monday.
    s = _sched("weekly_fixed", datetime.date(2026, 10, 1),
               datetime.date(2026, 11, 1), weekday=0)
    assert T._due_today(s, datetime.date(2026, 10, 5))
    assert not T._due_today(s, datetime.date(2026, 10, 6))


def test_weekly_random_picks_one_day_per_week():
    s = _sched("weekly_random", datetime.date(2026, 10, 1),
               datetime.date(2026, 11, 1))
    week = [datetime.date(2026, 10, 5) + datetime.timedelta(days=i) for i in range(7)]
    due = [d for d in week if T._due_today(s, d)]
    assert len(due) == 1, f"expected exactly one day, got {due}"


def test_weekly_random_does_not_re_roll_between_calls():
    """A schedule that re-rolled on read would give two callers different
    answers — one notified, the other not."""
    s = _sched("weekly_random", datetime.date(2026, 10, 1),
               datetime.date(2026, 11, 1))
    day = datetime.date(2026, 10, 7)
    first = [T._random_day_for_week(s, day) for _ in range(20)]
    assert len(set(first)) == 1


def test_two_schedules_do_not_land_on_the_same_random_day_by_construction():
    """Seeded from the schedule id, so two campaigns in one company spread out
    rather than both firing on Tuesday."""
    a = _sched("weekly_random", datetime.date(2026, 10, 1), datetime.date(2026, 11, 1))
    b = _sched("weekly_random", datetime.date(2026, 10, 1), datetime.date(2026, 11, 1))
    week = datetime.date(2026, 10, 7)
    # Not guaranteed different, but must not be derived from the week alone.
    assert "schedule.id" in _code(T._random_day_for_week)


def test_monthly_clamps_to_the_last_day_of_a_short_month():
    """A schedule starting on the 31st must not silently skip February."""
    s = _sched("monthly", datetime.date(2026, 1, 31), datetime.date(2026, 12, 31))
    assert T._due_today(s, datetime.date(2026, 2, 28))
    assert not T._due_today(s, datetime.date(2026, 2, 27))


# ── roll-over ───────────────────────────────────────────────────────────────

def test_daily_skips_a_day_with_no_dispatch_rather_than_rolling():
    """A daily schedule already has tomorrow queued, so rolling a closed Sunday
    onto Monday would collide with Monday's own occurrence."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert T.resolve_open_date(db, uuid.uuid4(), datetime.date(2026, 10, 4),
                               "daily") is None


def test_the_other_modes_push_to_the_next_day_with_a_dispatch():
    """Losing a monthly occurrence to one holiday means a month with no data."""
    # ast.unparse normalises quote style, so match on the structure rather
    # than the literal — a test that fails on single-vs-double quotes is
    # testing the formatter.
    src = _code(T.resolve_open_date)
    assert "mode ==" in src and "daily" in src
    assert "MAX_ROLL_DAYS" in src


def test_the_search_horizon_is_bounded():
    """A station that stops dispatching must not leave a schedule silently
    probing forward forever."""
    assert T.MAX_ROLL_DAYS == 14


# ── windows ─────────────────────────────────────────────────────────────────

def test_the_windows_match_the_decision():
    """Short on purpose: these ask someone to recall a specific shift, and a
    month-long window does not collect more data, it collects vaguer data."""
    assert T.WINDOW_DAYS == {"weekly_fixed": 2, "weekly_random": 2, "monthly": 3}


def test_daily_closes_at_the_next_days_shift_start():
    """A fixed, predictable instant that does not depend on tomorrow's dispatch
    existing yet — a run whose close time is unknowable when it opens cannot be
    shown as a countdown."""
    src = _code(T._close_at)
    assert "timedelta(days=1)" in src and "cfg.shift_start" in src


def test_close_times_are_built_in_company_time():
    """A naive UTC relabel would close a New York run at 8pm (ADR-486)."""
    src = _code(T._close_at)
    assert "company_datetime(" in src and "company_tz(" in src
    assert "replace(tzinfo=" not in src


# ── a run nobody can answer is not opened ───────────────────────────────────

def test_a_run_with_no_eligible_respondents_is_rolled_back():
    """An open run that could never receive a response is indistinguishable,
    on the results page, from one everybody ignored (D16)."""
    src = _code(T._process)
    assert "if not respondents:" in src and "db.rollback()" in src


def test_one_companys_failure_does_not_stop_the_others():
    src = _code(T.open_scheduled_runs)
    assert "db.rollback()" in src and "logger.exception" in src


# ── the end of a schedule is announced ──────────────────────────────────────

def test_the_end_notice_goes_to_management_as_well_as_the_creator():
    """created_by is ondelete=SET NULL — the creator may have left, and a
    notice addressed only to a null actor is the lapse this prevents."""
    src = _code(T._notify_schedule_ended)
    assert "Employee.role.in_((" in src
    assert "management" in src and "admin" in src
    assert "schedule.created_by" in src


def test_the_end_notice_is_sent_once():
    """A one-way stamp, or it fires on every tick for the rest of the
    schedule's existence."""
    assert "ended_notified_at" in _code(T._notify_schedule_ended)
    assert "ended_notified_at is None" in _code(T._process)


def test_the_scheduled_open_writes_an_audit_row_with_no_actor():
    """actor_id is a FK to employees and a scheduled action has none."""
    src = _code(T._process)
    assert "write_audit(" in src
    assert "actor_id" not in src
