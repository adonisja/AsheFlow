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

    `notification_id` is the primary key: one acknowledgement per notification,
    and a second attempt is an idempotency question rather than a new row. The
    alternative — a composite key with `employee_id` — would allow two rows for
    one notification, and a notification addresses exactly one employee.
    """

    __tablename__ = "notification_acknowledgements"

    notification_id = Column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"),
        primary_key=True,
    )
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
