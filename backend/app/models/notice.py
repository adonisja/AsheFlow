"""Notices — recurring reminders scheduled against the tenant's own clock (ADR-488).

WHY THIS IS NOT A `SPEC` ENTRY
==============================

ADR-487 D1 made every notification type a declared registry constant, and that
is right for the 85 types that announce something that HAPPENED. A notice is the
other thing: it fires because a TIME ARRIVED.

    An INFO announces that something happened.
    A NOTICE fires because a time arrived.

So a notice needs a schedule, an audit trail and a retirement path, none of
which a module-level constant has or should have. The TIER is declared
(`Severity.NOTICE`); the INSTANCES are rows.

WHY PLATFORM AND TENANT NOTICES SHARE ONE TABLE
===============================================

Four of this product's beat tasks notify people on a fixed SERVER hour, which is
wrong for every tenant outside the server's timezone — a West Coast employee got
their MFA warning at 13:30, and a tenant whose drivers return at 20:00 was
reminded to file a fuel log three hours before anyone could have.

Those four are not a different kind of thing from a manager's "remember to log
your break". They are notices the platform happens to have written. So they are
seeded as ORDINARY ROWS, exactly as ADR-485 D8 ships the driver and captain
campaigns, and for the reason that ADR gives:

    A special-cased built-in is a second code path that drifts from the one
    admins use — and the one admins use is the one that gets tested.

`origin` records which is which, and it decides exactly three policy questions
(who may edit the text, whether `ends_on` is required, whether a second pass is
offered). Everything else treats them identically.

THE ANCHOR IS THE UNIT
======================

A platform notice does not declare WHEN it fires. It declares what tenant time
it fires RELATIVE TO, and the tenant's own config supplies the clock:

    fuel_log_missing   ->  SHIFT_END - 15 min
    dispatch_unfinal.  ->  DISPATCH_CUTOFF - 5 min
    mfa_warning        ->  FIXED_LOCAL 16:30      (no config needed)
    timecard_scan      ->  LOCAL_MIDNIGHT         (no config needed)

Two of the four need no tenant config at all, which is why this migration is not
uniformly expensive: the hard part is only the two that key on columns, and both
of those columns already exist.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Integer, String, Time, func, text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class Anchor(StrEnum):
    """What tenant time a notice fires relative to.

    The first three name a `CompanyConfig` column directly, so `getattr(cfg,
    anchor)` resolves them — which is why the member VALUES are the column
    names rather than tidier labels. The last two need no tenant config.

    Every config-backed anchor is `Column(Time, nullable=True)` with NO default
    (the "default 09:00" on the cutoff is a comment), so resolution can return
    None and the sweep must handle that by SKIPPING AND REPORTING — see
    `services/notices.py`.
    """

    SHIFT_START = "shift_start"
    SHIFT_END = "shift_end"
    DISPATCH_CUTOFF = "dispatch_confirmation_cutoff"
    FIXED_LOCAL = "fixed_local"
    LOCAL_MIDNIGHT = "local_midnight"


#: Anchors that read a nullable `CompanyConfig` column, so a tenant that has not
#: configured them cannot be served. Named rather than derived by exclusion: a
#: future anchor added to the enum should have to decide which side it is on.
CONFIG_BACKED_ANCHORS: frozenset[Anchor] = frozenset({
    Anchor.SHIFT_START, Anchor.SHIFT_END, Anchor.DISPATCH_CUTOFF,
})


class Condition(StrEnum):
    """When a due notice actually sends, and to whom.

    A CLOSED enum of platform predicates, not an expression a tenant can write
    (ADR-488 D5). A tenant-expressible condition is a query language, and a
    query language against tenant data reached from a scheduler is a surface
    this system has no reason to open. A tenant authoring a notice gets ALWAYS.

    The condition also decides the AUDIENCE: `DRIVER_MISSING_FUEL_LOG` returns
    the drivers who have not filed, which is both the firing test and the
    recipient list. That is what makes ADR-487 D2's "name the trucks" fix and
    this migration the same change.
    """

    ALWAYS = "always"
    UNFINALIZED_DISPATCH_EXISTS = "unfinalized_dispatch_exists"
    DRIVER_MISSING_FUEL_LOG = "driver_missing_fuel_log"   # field_ops.FuelMileageLog
    MFA_DEADLINE_WITHIN_WARNING = "mfa_deadline_within_warning"
    # No TIMECARD_MISMATCH_SCAN: ADR-488 D5a. `detect_timecard_mismatches`
    # db.add()s TimeCardAdjustment rows — it IS the scan, not a reminder that
    # one happened. As a notice, an unconfigured anchor would silently skip the
    # DETECTION rather than a message. A notice reminds somebody that a time
    # arrived; if skipping it would skip WORK, it is a task.


#: Conditions a tenant may select when authoring. Everything else reads data
#: only the platform's own code understands.
TENANT_SELECTABLE_CONDITIONS: frozenset[Condition] = frozenset({Condition.ALWAYS})


class NoticeOrigin(StrEnum):
    PLATFORM = "platform"
    TENANT = "tenant"


class NoticeTemplate(Base):
    """The notice itself. Outlives every firing it produces."""

    __tablename__ = "notice_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    origin = Column(String(16), nullable=False, default=NoticeOrigin.TENANT.value)

    # Stable identity for a platform notice, so a backfill finds the row it
    # already seeded rather than duplicating it. NULL for tenant-authored.
    seed_key = Column(String(64), nullable=True)

    label = Column(String(60), nullable=False)
    # 280 chars: the ticker renders one line and its scroll duration scales with
    # content, so a long body is a denial of service on the strip. See the cap
    # reasoning in ADR-488 D10.
    body = Column(String(280), nullable=False)

    anchor = Column(String(32), nullable=False)
    offset_minutes = Column(Integer, nullable=False, default=0)
    # Only meaningful for anchor='fixed_local'; the CheckConstraint below makes
    # that a schema rule rather than a convention.
    at_local = Column(Time, nullable=True)

    condition = Column(String(48), nullable=False, default=Condition.ALWAYS.value)
    audience = Column(String(32), nullable=False)   # a role name, or 'all'

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # One platform notice per key per tenant — what makes the backfill
        # idempotent. Partial, so tenant notices are unconstrained.
        Index(
            "uq_notice_seed_per_company", "company_id", "seed_key",
            unique=True, postgresql_where=text("seed_key IS NOT NULL"),
        ),
        # A fixed-local notice without a time would resolve to None and be
        # skipped forever, looking like a config problem rather than a bad row.
        CheckConstraint(
            "anchor <> 'fixed_local' OR at_local IS NOT NULL",
            name="ck_notice_fixed_local_needs_time",
        ),
        CheckConstraint(
            "origin IN ('platform', 'tenant')",
            name="ck_notice_origin",
        ),
    )


class NoticeSchedule(Base):
    """When a notice recurs. The field list is `CampaignSchedule`'s, deliberately.

    ADR-485 D12 already solved recurrence — `mode`, `weekday`, bounded
    `starts_on`/`ends_on`, `ended_notified_at` — and `tasks/campaign_runs.py`
    has the company-local date resolution to match. This ADR's job is a message
    and an audience, not a scheduler.

    Two differences from `CampaignSchedule`, both load-bearing:

    `ends_on` is NULLABLE here. ADR-485 D12 requires every campaign schedule to
    END, which is right for something a manager set up and forgot. A PLATFORM
    notice anchored to `shift_end` should not expire, because the condition it
    reports on recurs indefinitely. The CheckConstraint below binds the rule to
    tenant notices only, in the schema rather than only in the router, so a seed
    script cannot create an endless tenant notice by accident.

    `fired_on` + `fired_count` are the idempotency. The sweep runs every 15
    minutes; without a stamp, halving the interval doubles the messages — which
    is the failure that makes people nervous about sweeps in the first place.
    """

    __tablename__ = "notice_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    notice_id = Column(
        UUID(as_uuid=True), ForeignKey("notice_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    mode = Column(String(16), nullable=False)   # daily|weekly_fixed|weekly_random|monthly
    weekday = Column(Integer, nullable=True)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=True)
    ended_notified_at = Column(DateTime(timezone=True), nullable=True)

    fired_on = Column(Date, nullable=True, index=True)
    fired_count = Column(Integer, nullable=False, default=0)

    # A SECOND pass, N minutes after the first, for a condition that can still
    # resolve between them. `remind_fuel_log_missing` fires at 17:00 AND 18:30
    # on purpose — "a second pass re-notifies any still-missing drivers, this
    # handles late returns" — and a first draft of ADR-488 would have silently
    # reduced it to one. Not offered to tenant authors: two anchors is clearer
    # than a repeat control, and it counts twice against the cap, which is the
    # honest accounting.
    repeat_after_minutes = Column(Integer, nullable=True)
    max_fires_per_day = Column(Integer, nullable=False, default=1)

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "mode IN ('daily', 'weekly_fixed', 'weekly_random', 'monthly')",
            name="ck_notice_schedule_mode",
        ),
        # A weekly_fixed schedule with no weekday has no day to fire on.
        CheckConstraint(
            "mode <> 'weekly_fixed' OR weekday IS NOT NULL",
            name="ck_notice_weekly_needs_weekday",
        ),
        CheckConstraint(
            "max_fires_per_day >= 1",
            name="ck_notice_fires_positive",
        ),
        # A second pass with no interval would fire twice in the same sweep tick.
        CheckConstraint(
            "max_fires_per_day = 1 OR repeat_after_minutes IS NOT NULL",
            name="ck_notice_repeat_needs_interval",
        ),
    )
