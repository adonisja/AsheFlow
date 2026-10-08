"""The sweep replaces four server-hour beat entries, and the registry knows it (ADR-488).

WHY A SOURCE-WALKING TEST FOR THE BEAT SCHEDULE
===============================================

The defect being guarded is an ADDITION: somebody adds a notification task on a
fixed server hour, because that is the idiom the file is full of. No request
fails and no test goes red — the notification just arrives at 16:30 server time
for a tenant in Los Angeles. A behavioural test cannot see a crontab that should
not be there.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CELERY = ROOT / "app/celery_app.py"
SEEDS = ROOT / "app/services/notice_seeds.py"


def _code_only(src: str) -> str:
    """Comments stripped. Every absence assertion below needs it: these files
    EXPLAIN the entries they removed, naming them."""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(l.split("#", 1)[0] for l in src.splitlines())


class TestTheSupersededEntriesAreGone:
    """Four entries deleted. Their functions are kept (still invocable by hand,
    and `notice_conditions` lifts BANDS from one of them), but nothing schedules
    them — a scheduled caller would reintroduce the server-hour bug."""

    _GONE = (
        "warn-before-mfa-deadline",
        "dispatch-finalization-reminder",
        "fuel-log-reminder-first",
        "fuel-log-reminder-second",
    )

    @pytest.mark.parametrize("key", _GONE)
    def test_the_entry_is_not_scheduled(self, key):
        assert f'"{key}"' not in _code_only(CELERY.read_text()), (
            f"{key} is scheduled again; it fires on a fixed SERVER hour, which "
            f"means nothing to any tenant outside the server's zone — add or "
            f"retime a notice row instead (ADR-488)"
        )

    def test_the_sweep_replaced_them(self):
        assert '"fire-due-notices"' in _code_only(CELERY.read_text())

    def test_the_functions_still_exist(self):
        """Deleting them would break `notice_conditions._mfa_deadline_approaching`,
        which lifts BANDS and the window arithmetic rather than re-deriving it —
        including the ADR-377 rule that privileged roles have no grace at all."""
        from app.tasks.dispatch_alerts import alert_finalization_deadline
        from app.tasks.eod_reminders import remind_fuel_log_missing
        from app.tasks.mfa_deadline_warnings import BANDS, warn_before_mfa_deadline

        assert callable(alert_finalization_deadline)
        assert callable(remind_fuel_log_missing)
        assert callable(warn_before_mfa_deadline)
        assert BANDS, "BANDS is what notice_conditions imports"


class TestTheSweepInterval:
    def test_it_runs_every_fifteen_minutes(self):
        """Costed rather than asserted: 96 ticks/day against
        resolve_pending_addresses and check_integration_health at 144 each — and
        the latter makes three outbound HTTP calls per tick where this makes
        zero."""
        src = _code_only(CELERY.read_text())
        block = src[src.index('"fire-due-notices"'):]
        block = block[:block.index("},")]
        assert 'minute="*/15"' in block

    def test_it_is_not_merged_into_another_sweep(self):
        """ADR-487 D4d: the beat tasks already run in parallel, and merging
        would serialise work that currently is not."""
        src = _code_only(CELERY.read_text())
        block = src[src.index('"fire-due-notices"'):]
        block = block[:block.index("},")]
        assert block.count('"task"') == 1


class TestTheMismatchScanStaysATask:
    """ADR-488 D5a. It db.add()s TimeCardAdjustment rows, so it IS the scan
    rather than a reminder that one happened."""

    def test_it_still_has_its_own_entry(self):
        assert '"run-adp-vs-flex-mismatch-detection-daily"' in _code_only(CELERY.read_text())

    def test_it_moved_off_the_mid_shift_hour(self):
        """12:00 server examined a day that was not over."""
        src = _code_only(CELERY.read_text())
        block = src[src.index('"run-adp-vs-flex-mismatch-detection-daily"'):]
        block = block[:block.index("},")]
        assert "hour=12" not in block, "the scan still runs mid-shift"
        assert "hour=0" in block

    def test_it_lands_before_the_escalation_that_depends_on_it(self):
        """Escalation raises the urgency of adjustments this task CREATES, so
        detection after escalation means a weekend adjustment waits a full day
        for its first escalation."""
        src = _code_only(CELERY.read_text())

        def minute_of(key):
            b = src[src.index(f'"{key}"'):]
            b = b[:b.index("},")]
            m = re.search(r"minute=(\d+)", b)
            return int(m.group(1))

        assert minute_of("run-adp-vs-flex-mismatch-detection-daily") < \
               minute_of("escalate-adp-mismatch-statuses")


class TestTheSeeds:
    def test_three_notices_not_four(self):
        """ADR-487 D4d listed four; the scan is not one of them (D5a)."""
        from app.services.notice_seeds import PLATFORM_NOTICES
        assert len(PLATFORM_NOTICES) == 3
        assert {s.seed_key for s in PLATFORM_NOTICES} == {
            "dispatch_unfinalized", "fuel_log_missing", "mfa_deadline_warning",
        }

    def test_the_fuel_log_keeps_its_second_pass(self):
        from app.services.notice_seeds import PLATFORM_NOTICES
        fuel = next(s for s in PLATFORM_NOTICES if s.seed_key == "fuel_log_missing")
        assert fuel.passes == 2, (
            "the old task fired at 17:00 AND 18:30 on purpose — a second pass "
            "re-notifies drivers who returned late"
        )
        assert fuel.repeat_after_minutes is not None

    def test_every_other_notice_fires_once(self):
        from app.services.notice_seeds import PLATFORM_NOTICES
        for s in PLATFORM_NOTICES:
            if s.seed_key == "fuel_log_missing":
                continue
            assert s.passes == 1, f"{s.seed_key} asks twice; only the fuel log should"

    def test_a_fixed_local_seed_carries_a_time(self):
        """The CheckConstraint requires it, so a seed without one cannot insert."""
        from app.models.notice import Anchor
        from app.services.notice_seeds import PLATFORM_NOTICES
        for s in PLATFORM_NOTICES:
            if s.anchor == Anchor.FIXED_LOCAL:
                assert s.at_local is not None, f"{s.seed_key} would violate the constraint"

    def test_every_body_fits_the_column(self):
        """280 chars: the ticker renders one line and its scroll duration scales
        with content."""
        from app.services.notice_seeds import PLATFORM_NOTICES
        for s in PLATFORM_NOTICES:
            assert len(s.body) <= 280, f"{s.seed_key} body is {len(s.body)} chars"
            assert len(s.label) <= 60


class TestTheNoticeTypeIsDeclared:
    """`write_notification` REFUSES an undeclared type (ADR-487 D1), so the
    sweep's type must be in SPEC or every notice raises and the sweep's
    per-notice try/except swallows it — which is the exact bug ADR-487's own
    integration alerts hit."""

    def test_it_resolves(self):
        from app.services.notify import _resolve_raisable
        from app.tasks.notice_sweep import NOTICE_TYPE
        assert _resolve_raisable(NOTICE_TYPE).label

    def test_it_is_the_notice_tier(self):
        from app.services.notification_spec import Severity, resolve_spec
        from app.tasks.notice_sweep import NOTICE_TYPE
        assert resolve_spec(NOTICE_TYPE).severity is Severity.NOTICE

    def test_it_is_ticker_only(self):
        """ADR-488 D8, three omissions each deliberate: no BANNER (a daily
        reminder in banner space is how a banner stops being read), no PUSH (a
        daily push is how someone disables push for everything, URGENT
        included), no DISCORD (the same mistake on a channel the tenant does not
        control)."""
        from app.services.notification_spec import Channel, resolve_spec
        from app.tasks.notice_sweep import NOTICE_TYPE
        ch = resolve_spec(NOTICE_TYPE).channels
        assert Channel.TICKER in ch
        for forbidden in (Channel.BANNER, Channel.PUSH, Channel.DISCORD):
            assert forbidden not in ch, f"the NOTICE tier routes to {forbidden.name}"


class TestTheRenderIsForgiving:
    """A body with a placeholder the condition does not supply would raise
    KeyError inside a Celery task, where the traceback is a log line nobody
    reads."""

    def test_an_unknown_placeholder_renders_as_itself(self):
        from app.tasks.notice_sweep import _render
        assert _render("there are {count} {noun}", {"count": 3}) == "there are 3 {noun}"

    def test_a_malformed_body_is_sent_verbatim(self):
        from app.tasks.notice_sweep import _render
        assert _render("an unbalanced { brace", {"x": 1}) == "an unbalanced { brace"

    def test_no_context_is_a_passthrough(self):
        from app.tasks.notice_sweep import _render
        assert _render("plain text", {}) == "plain text"


class TestTheSweepIsTenantScopedPerRow:
    """Dimension 1 on a deliberately cross-tenant query.

    The sweep reads every company's schedules in one pass — that is the design,
    and it is why it costs two queries per tick instead of two per tenant. What
    makes it safe is that each ROW is then scoped by its own
    `schedule.company_id`, and that the join checks company_id on BOTH sides.

    Why the join predicate matters even with a foreign key: a join adds a second
    table, and filtering one side does not scope the other. A schedule whose
    company_id disagreed with its template's would make the sweep read tenant
    A's config and notify tenant A's employees with tenant B's notice TEXT. The
    FK makes that hard to create and not impossible — a bad backfill or a
    company merge would do it.
    """

    def test_the_join_scopes_both_sides(self):
        import inspect
        from app.tasks import notice_sweep

        src = _code_only(inspect.getsource(notice_sweep.fire_due_notices))
        assert "NoticeSchedule.company_id == NoticeTemplate.company_id" in src, (
            "the join matches on notice_id alone, so a cross-tenant schedule/"
            "template pair would render one tenant's text to another's employees"
        )

    def test_every_downstream_call_uses_the_rows_own_company(self):
        """Not the loop variable from an outer scope, and not a cached value —
        each per-row call must key on `schedule.company_id`."""
        import inspect
        from app.tasks import notice_sweep

        src = _code_only(inspect.getsource(notice_sweep._process_one))
        # the recipient resolution and the notification write are the two that
        # would leak if they used anything else
        assert "resolve_recipients(" in src
        assert src.count("schedule.company_id") >= 4, (
            "a per-row path stopped keying on the row's own company_id"
        )
        assert "company_id=schedule.company_id" in src, (
            "the notification write must address the schedule's own tenant"
        )
