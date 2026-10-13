"""When a GATE must not be a gate (ADR-494 D6, D3, D8).

A GATE has no exit but its own action. That is defensible only while the action
is actually available, so something has to decide when it is not — and the two
surfaces must agree about it.

THE SERVER DECIDES
==================
`channels` is already resolved per read from the registry (ADR-487 D4), so the
degradation happens there: the server omits `gate` and carries `prompt`, and the
clients never implement a downgrade rule. They cannot disagree about a rule they
do not have, which is the drift the D4 mobile pass spent a session closing.

The alternative -- ship `gate` and let each client notice the action is missing
-- needs the same logic written twice in two languages, and the failure mode is
one surface walling a user the other lets through.

THREE REASONS A GATE DEGRADES
=============================
1. **It expired** (D8). `Notification.expires_at` already exists. The thing the
   gate protected no longer applies, and a stale gate from a reverted role change
   would otherwise lock someone out permanently with nothing to acknowledge.

2. **Its deadline is unresolvable** (D3). `timecard_mismatch` escalates toward
   `ADPPayPeriod.close_deadline`. No resolvable deadline means no escalation
   clock, so it stays a PROMPT -- never a wall, and never silence. ADR-212
   recorded the silent version of this as a P0: *"empty adp_pay_periods silently
   disables mismatch detection entirely."*

3. **Its destination does not exist**. `graduation` and `operating_mode_change`
   point at `/my-role`. An unseeded tenant has no row, so the prompt's only
   control would 404 -- strictly worse than the modal it replaced.

WHAT THIS DELIBERATELY DOES NOT DO
==================================
It never ADDS a channel. A type that is not a GATE in the registry cannot become
one here, so reading this module tells you the complete set of ways a gate can
appear, and it is one: the registry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services.notification_spec import Channel

logger = logging.getLogger(__name__)

#: Types whose gate is bounded by an external deadline. The value names the
#: reason, which is what the caller logs and what a test asserts against.
_DEADLINE_GATED = {"timecard_mismatch"}

#: Types whose only exit is a `/my-role` row. Derived from SPEC rather than
#: typed, so a new type pointing at /my-role is covered without editing this.
_MY_ROLE_ROUTE = "/my-role"


def _types_needing_role_guide() -> frozenset[str]:
    """Types whose action targets /my-role, read from the registry.

    Derived, not listed. A fourth type pointing at /my-role gets this protection
    without anyone remembering to add it here -- the completeness direction
    ADR-499's lesson argues for: enumerate the world, do not maintain a list.
    """
    from app.services.notification_spec import SPEC

    return frozenset(
        t for t, s in SPEC.items()
        if any(a.route == _MY_ROLE_ROUTE for a in s.actions)
    )


def _timecard_gate_is_live(db: Session, row) -> tuple[bool, str]:
    """Has `timecard_mismatch` reached the day before its pay period closes?

    Returns `(gate_holds, reason)`. The reason is logged and asserted on; it is
    never shown to a user.

    The gate holds only inside the final day. Before that the reader can still
    work and be asked again (the owner's requirement: *"someone who skipped
    should be asked again on next login or next day"*), so it stays a PROMPT.
    """
    from app.models.timecard_adjustments import TimeCardAdjustment
    from app.models.adp_pay_period import ADPPayPeriod

    adj = (
        db.query(TimeCardAdjustment, ADPPayPeriod.close_deadline)
        .join(ADPPayPeriod, TimeCardAdjustment.pay_period_id == ADPPayPeriod.id)
        .filter(
            # Dimension 1: BOTH sides scoped. The join does not imply it --
            # a pay period is company-scoped too, and filtering only the
            # adjustment would read another tenant's deadline.
            TimeCardAdjustment.company_id == row.company_id,
            ADPPayPeriod.company_id == row.company_id,
            TimeCardAdjustment.employee_id == row.employee_id,
            TimeCardAdjustment.employee_signed_off_at.is_(None),
        )
        .order_by(ADPPayPeriod.close_deadline.asc())
        .first()
    )

    if adj is None:
        # No unsigned adjustment for this person. The notification outlived the
        # thing it was about -- already signed off, or resolved by someone else.
        # Nothing to gate toward, so do not gate.
        return False, "no_unsigned_adjustment"

    _, close_deadline = adj
    if close_deadline is None:
        # Cannot happen through the ORM (NOT NULL + FK), but a direct-SQL
        # backfill could. Degrade rather than compare against None, which
        # raises inside a read of fifty rows.
        return False, "no_close_deadline"

    now = datetime.now(timezone.utc)
    deadline = close_deadline
    if deadline.tzinfo is None:
        # The column is DateTime(timezone=True) but SQLite -- which the test
        # mirror uses -- drops tzinfo. Attaching UTC here is a READ of a value
        # already stored as UTC, not the naive-relabel ADR-485 D18 banned:
        # that bug attached UTC to a LOCAL wall-clock Time.
        deadline = deadline.replace(tzinfo=timezone.utc)

    seconds_left = (deadline - now).total_seconds()
    if seconds_left <= 86400:
        return True, "within_final_day"
    return False, f"deadline_in_{int(seconds_left // 3600)}h"


def degrade_channels(db: Session | None, row, channels: list[str]) -> list[str]:
    """`channels` with `gate` removed where the gate cannot be honoured.

    Takes the already-resolved channel name list so this stays a pure
    transformation of the wire value -- the registry is read once, in
    `_resolve_for_read`, and this narrows the result.

    `db=None` disables the checks that need a query and keeps the ones that do
    not (expiry). That is for callers with no session, and it fails SAFE: a gate
    that cannot be verified becomes a prompt rather than a wall.
    """
    if "gate" not in channels:
        return channels

    def _as_prompt(reason: str) -> list[str]:
        out = [c for c in channels if c != "gate"]
        if "prompt" not in out:
            out.append("prompt")
        logger.info(
            "notification %s (%s) degraded gate->prompt: %s",
            getattr(row, "id", "?"), getattr(row, "type", "?"), reason,
        )
        return sorted(out)

    # 1. Expired (D8). No query needed, so it applies even without a session.
    expires_at = getattr(row, "expires_at", None)
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return _as_prompt("expired")

    if db is None:
        return _as_prompt("no_session_to_verify")

    notif_type = getattr(row, "type", "")

    # 2. The deadline the gate escalates toward (D3).
    if notif_type in _DEADLINE_GATED:
        holds, reason = _timecard_gate_is_live(db, row)
        if not holds:
            return _as_prompt(reason)

    # 3. The destination the only exit points at.
    if notif_type in _types_needing_role_guide():
        from app.models.role_guide import RoleGuide

        exists = (
            db.query(RoleGuide.id)
            .filter(RoleGuide.company_id == row.company_id)
            .first()
            is not None
        )
        if not exists:
            return _as_prompt("no_role_guide_rows")

    return channels


#: The channels that make a notification interrupt. Settling removes both.
_INTERRUPTIVE = ("gate", "prompt")


def drop_if_settled(db: Session | None, row, channels: list[str]) -> list[str]:
    """`channels` without `gate`/`prompt` once the notification has a final answer (ADR-505 D2).

    Before ADR-505 nothing did this: the list endpoint returns read rows, this
    module never consulted acknowledgements, and neither client filtered answered
    rows, so a confirmed prompt came back on every launch until the 3-day prune.

    A SEPARATE function from `degrade_channels`, deliberately. That one decides
    whether a gate can be HONOURED and never adds or removes anything else;
    this one decides whether the conversation is OVER, and removes both
    interruptive channels while leaving banner/push/inbox alone -- the record of
    the notification stays visible, it just stops interrupting.

    Queries only for rows that interrupt, which is a handful per page, not one
    query per notification. Without a session it cannot check and changes
    nothing; the client treats the resulting 409 as "already settled", so the
    cost of that path is one redundant dialog, never a lost answer.
    """
    if db is None or not any(c in channels for c in _INTERRUPTIVE):
        return channels

    from app.models.role_guide import FINAL_ACK_ACTIONS, NotificationAcknowledgement

    settled = (
        db.query(NotificationAcknowledgement.id)
        .filter(
            # Dimension 1: scoped, though the notification id already implies it.
            NotificationAcknowledgement.company_id == row.company_id,
            NotificationAcknowledgement.notification_id == row.id,
            NotificationAcknowledgement.action.in_(FINAL_ACK_ACTIONS),
        )
        .first()
    )
    if settled is None:
        return channels
    return sorted(c for c in channels if c not in _INTERRUPTIVE)
