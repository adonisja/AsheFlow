"""What a role is told it may do, and who has acknowledged being told (ADR-494).

TWO TABLES, ONE REASON EACH
===========================

`role_guides` is the content behind `/my-role`: one row per (company, role),
seeded by the platform and editable by the tenant. `notification_acknowledgements`
records that a person chose something, as distinct from having been shown it.

WHY THE CONTENT IS A ROW AND NOT A TSX BLOCK
============================================

Ten roles, content differing per operating mode (ADR-305 changes half the
surface), and it has to stay true as features ship. Hardcoded in a component it
goes stale silently: the day we ship a feature that changes what a dispatcher
does, nothing reminds us the page says otherwise.

Seeded as ordinary rows instead, for the reason ADR-485 D8 gives and ADR-488 D1
reused:

    a special-cased built-in is a second code path that drifts from the one
    admins use -- and the one admins use is the one that gets tested

`seed_key` is what lets the platform ship a NEW version of a guide later without
duplicating a tenant's row, and what makes the backfill idempotent.

WHY AN ACKNOWLEDGEMENT IS NOT A READ FLAG
=========================================

`Notification.is_read` is set by RENDERING. This is set by a person CHOOSING.
Conflating them is how a prompt closed by a stray tap becomes evidence of
consent -- and for `timecard_mismatch` that evidence is what a payroll dispute
six weeks later turns on.

`action` has three values, not two. ADR-487 D8 specified `confirmed` and
`skipped`, and the distinction is the point: an employee who CONFIRMED the hours
and one who SKIPPED have told you different things. `unavailable` is the third,
because ADR-494 D6 degrades a gate whose action cannot be offered -- and a row
reading `skipped` when the person was never offered the choice asserts a declined
decision that was never presented.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text, func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class AckAction(StrEnum):
    """What the person actually did."""

    CONFIRMED = "confirmed"
    SKIPPED = "skipped"
    #: The gate degraded because its action could not be offered (ADR-494 D6):
    #: no pay-period row to resolve a deadline, or no role guide to link to.
    #: NOT the same as skipped — nobody declined anything.
    UNAVAILABLE = "unavailable"


class RoleGuide(Base):
    """What this company tells one role it may do.

    Keyed on (company_id, role, operating_mode) rather than (company_id, role):
    ADR-305 changes half the app's surface, so what a walker does in workforce
    mode is not what they do in full mode, and one body cannot be true for both.
    """

    __tablename__ = "role_guides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    role = Column(String(32), nullable=False)
    #: 'full' | 'workforce'. NOT nullable: a guide that claims to apply to both
    #: modes is the hardcoded-block problem in a row.
    operating_mode = Column(String(16), nullable=False)

    title = Column(String(80), nullable=False)
    #: Markdown-ish prose, rendered by React (escaped). Text rather than a capped
    #: String because this is a page, not a notification body — the ticker's
    #: 280-char reasoning (ADR-488 D10) does not apply to a surface the reader
    #: navigated to deliberately.
    body = Column(Text, nullable=False)

    #: Set on the platform's seeded rows, NULL on a row a tenant created from
    #: scratch. A tenant EDIT keeps the seed_key and sets `edited_at`, which is
    #: what lets DELETE revert to the seed rather than leaving a role with no
    #: content (ADR-494 D9).
    seed_key = Column(String(64), nullable=True)
    seed_version = Column(String(16), nullable=True)

    edited_at = Column(DateTime(timezone=True), nullable=True)
    edited_by = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # One guide per role per mode per tenant. This is what makes the seeder
        # idempotent and what makes "edit the walker's full-mode guide"
        # unambiguous.
        Index("uq_role_guide", "company_id", "role", "operating_mode", unique=True),
        CheckConstraint(
            "operating_mode IN ('full', 'workforce')",
            name="ck_role_guide_mode",
        ),
        # An edit records WHO. A row with edited_at and no edited_by is a change
        # nobody owns, which is the ADR-490 failure in a different column.
        CheckConstraint(
            "(edited_at IS NULL) = (edited_by IS NULL)",
            name="ck_role_guide_edit_attributed",
        ),
    )


class NotificationAcknowledgement(Base):
    """That a person chose something about one notification.

    ## This row OUTLIVES the notification it refers to (ADR-494 D8 finding)

    The first version made `notification_id` the primary key with
    `ondelete="CASCADE"`, which was tidy and wrong. `prune_notifications`
    deletes notifications after **3 days** — and immediately once `expires_at`
    passes — so the cascade destroyed every acknowledgement three days after it
    was made.

    D7's entire justification is that *"an employee who confirmed the hours and
    one who skipped have told you different things, and a dispute six weeks
    later turns on which it was."* A record with a three-day life cannot serve
    that, and nothing would have reported the loss: the rows simply would not
    be there when someone looked.

    So the row stands alone as evidence. It carries a surrogate key, a
    `SET NULL` reference, and **snapshots of what the person was actually
    shown** — because after the notification is pruned the type and the message
    are not recoverable from anywhere else, and "they confirmed something" is
    not evidence of anything.

    This is the shape ADR-492's retention hold already uses: the record survives
    the thing it refers to, because the record is the point.

    ## Why `notification_id` is still UNIQUE

    One acknowledgement per notification, so a second attempt is an idempotency
    question (409) rather than a new row. That was the original PK's real job,
    and a unique constraint does it without tying the row's lifetime to the
    notification's.
    """

    __tablename__ = "notification_acknowledgements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: SET NULL, not CASCADE. The notification is pruned after 3 days; this row
    #: is the evidence and must not go with it. Nullable for the same reason.
    notification_id = Column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"),
        nullable=True, unique=True,
    )

    #: Snapshots, taken at acknowledgement time. Denormalised deliberately:
    #: once the notification row is pruned these are the only record of what
    #: the person was looking at when they chose, and an acknowledgement that
    #: cannot say WHAT was acknowledged is not evidence.
    notification_type = Column(String(64), nullable=False)
    message_snapshot = Column(Text, nullable=False)
    #: CASCADE, and that is a DECISION, not the default left in place.
    #:
    #: The sibling FK above is SET NULL precisely so this row outlives the
    #: notification it documents, so the asymmetry needs explaining.
    #:
    #: A hard employee delete is ON-DEMAND ERASURE (ADR-221). `delete_employee`
    #: calls `redact_employee_names` deliberately and its own 409 message tells
    #: the admin to "deactivate the employee instead of deleting". Evidence
    #: ABOUT a person who has been erased must go with them: keeping it would be
    #: the un-erased trace that erasure was asked to remove.
    #:
    #: The normal departure path preserves it. `deactivate_employee` stamps
    #: `deactivated_at` and the row survives as a TOMBSTONE with the FK intact
    #: (ADR-221), so `employee_id` stays resolvable indefinitely and the
    #: acknowledgement keeps its subject. The 6-month job redacts the NAME; it
    #: does not delete the employee row, so nothing here cascades.
    #:
    #: Why not ADR-492's answer -- refuse the delete while evidence exists? Its
    #: retention hold is RELEASABLE and owned by a person who placed it. An
    #: acknowledgement has no release, and no purge covers this table, so
    #: refusing on its existence would block erasure PERMANENTLY for anyone who
    #: ever answered a gate -- and would 409 a GDPR or Amazon erasure request
    #: with no way to comply. A conditional, clearable refusal and an
    #: unconditional, permanent one are different things.
    #:
    #: Why not SET NULL here too? The row would survive without its subject:
    #: "somebody at this company confirmed a timecard_mismatch" is evidence of
    #: nothing for the dispute this table exists to settle, AND it is a retained
    #: trace of an erased person. The worse half of both options.
    employee_id = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    acknowledged_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    action = Column(String(12), nullable=False)

    #: Which state the surface was in when they acted — 'gate' or 'prompt'.
    #: Carried because "they confirmed" means something different from a wall
    #: they could not escape than from a sheet they chose to engage with, and a
    #: dispute turns on exactly that distinction.
    shown_as = Column(String(8), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "action IN ('confirmed', 'skipped', 'unavailable')",
            name="ck_ack_action",
        ),
        CheckConstraint(
            "shown_as IN ('gate', 'prompt')",
            name="ck_ack_shown_as",
        ),
    )
