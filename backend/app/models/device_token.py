"""Where a push notification is delivered (ADR-487 D5).

Finding 2 of ADR-487 measured the gap: **no push infrastructure existed.** 25 of
the 86 declared notification types carry the `PUSH` channel and nothing delivered
any of them, so today's guarantee is *"you are told when you next open the app
and navigate to the right screen."* For a walker whose phone is in a cradle, an
injury alert waits.

This is the delivery address. One row per device per employee.

FIVE PROPERTIES, EACH ANSWERING A FAILURE THIS PROJECT HAS ALREADY HAD
======================================================================

`company_id` is present even though `employee_id` implies it. Every query filters
on it (audit Dimension 1), and a token is a delivery address for tenant data --
getting it wrong sends one tenant's notification to another's phone.

`ondelete="CASCADE"` on the employee, not SET NULL. A departed employee's device
must stop receiving, and a token with no owner is unroutable anyway. The opposite
choice from ADR-499's `_by_name` columns and from ADR-494's acknowledgement
`notification_id`, and for the opposite reason: there is nothing here worth
retaining. A device token is an address, not a record of anything.

`token` is GLOBALLY unique, not unique per employee. A phone handed from one
walker to another re-registers the same token against a new employee; without the
constraint the old row keeps delivering the first person's notifications to the
second. On conflict, registration MOVES the row rather than inserting -- see
`register_device`.

`revoked_at` rather than a delete, so a sign-out is distinguishable from a token
that was never registered. The ADR-443 lesson: a silent absence looks identical
to normal, and "this device signed out" and "this device never existed" need
different answers when someone asks why a push did not arrive.

`last_seen_at` so a stale token can be swept. Note `sweep_stale_devices`
(ADR-385) already exists for the MFA remembered-device table and is a DIFFERENT
concern -- that one is a trust TTL, this is a delivery address. This needs its
own sweep driven by SNS's own "endpoint disabled" signal rather than by age
alone, because a user who deletes the app never tells us and APNs reports it only
on the next send.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, String, func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class DevicePlatform(StrEnum):
    """The two platforms, matching what the mobile app reports.

    A StrEnum rather than free text because the value selects which SNS platform
    application an endpoint is created on -- a typo would create the endpoint on
    the wrong platform, or on none, and the failure would be silent.
    """

    IOS = "ios"
    ANDROID = "android"


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: Present even though employee_id implies it. See the module docstring.
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    platform = Column(String(10), nullable=False)

    #: The APNs/FCM registration token. 512 because FCM tokens run long and
    #: have grown historically; APNs device tokens are 64 hex.
    token = Column(String(512), nullable=False)

    #: The SNS platform endpoint, set when registration reaches SNS. NULL means
    #: "registered with us but not yet with SNS" -- which is the state every row
    #: is in while the platform ARNs are unset, and is why push being disabled
    #: does not block registration.
    endpoint_arn = Column(String(256), nullable=True)

    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    #: Set on sign-out, and set when SNS reports the endpoint disabled. NOT a
    #: delete: see the module docstring.
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # GLOBAL, not per-employee. The whole point: a re-registered token must
        # collide so registration can MOVE it.
        Index("uq_device_tokens_token", "token", unique=True),
        # Partial index for the send path, which only ever wants live rows for
        # one employee. Without it every fan-out scans revoked devices too.
        Index(
            "ix_device_tokens_live",
            "company_id", "employee_id",
            postgresql_where=Column("revoked_at").is_(None),
        ),
        CheckConstraint(
            "platform IN ('ios', 'android')",
            name="ck_device_token_platform",
        ),
    )
