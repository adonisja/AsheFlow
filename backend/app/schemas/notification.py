from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict

import logging

from app.services.notification_spec import Channel, Severity, Tone, resolve_spec

logger = logging.getLogger(__name__)


class NotificationResponse(BaseModel):
    """One notification, with its routing resolved from the registry (ADR-487 D4).

    WHY THE PRESENTATION FIELDS ARE RESOLVED HERE AND NOT STORED
    ============================================================

    `label`, `tone`, `icon` and `severity` come from SPEC at read time rather
    than from columns on the row. A stored label is a denormalised copy that
    goes stale the moment the wording is improved — and it will be, because
    several of the 82 read like log lines. Resolving on read means fixing a
    label fixes it everywhere, including rows already in the archive.

    The cost is that a type removed from SPEC breaks the read of its historical
    rows, which is why removal is two-step: stop raising it, then keep its entry
    in RETIRED rather than deleting it. `resolve_spec` checks RETIRED, so the
    four already-retired types still read.

    WHAT IS DELIBERATELY ABSENT: a colour
    =====================================

    `tone` is a semantic role ("bad"), never `#dc2626` and never `c.danger`.
    The two surfaces own different palettes on purpose — a React Native theme
    object and a Tailwind class string are not interchangeable — so the server
    says what the message MEANS and each client maps it to its own token.
    Sending a hex value from a Python file would put it into a native app's
    dark-mode palette, which is how a "danger" notification ends up unreadable
    on one of the two themes.
    """

    id: UUID
    employee_id: UUID
    type: str
    message: str
    is_read: bool
    created_at: datetime
    dispatch_date: Optional[date] = None
    expires_at: Optional[datetime] = None

    # Resolved from the registry, not columns. See the class docstring.
    severity: Severity
    label: str
    tone: Tone
    icon: str
    # The channel names this type routes to, lowercased ("banner", "ticker",
    # "push", ...). Sent rather than derived because "which types scroll in the
    # ticker" is NOT a function of severity: 52 types are INFO and only 20 carry
    # TICKER. The operative rule is about the message's SUBJECT —
    #
    #   INFO about the reader goes to the banner; INFO about a third party or
    #   about the system goes to the ticker
    #
    # — which no client can compute from `severity` alone. The alternative is a
    # 20-entry hardcoded list in each client, drifting from SPEC the first time
    # a type is added. ADR-487 D4b's own enumeration is already stale (it says
    # 18 of 80; the approved registry has 20 of 82), which is the argument.
    channels: list[str]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row) -> "NotificationResponse":
        """Build from an ORM row, resolving the registry fields.

        Used by the REST path. The SSE path cannot use this — it serialises to a
        plain dict for `json.dumps` — so both call `spec_fields()` instead of
        duplicating the resolution. Two serialisation paths for one model is
        exactly the shape where a partially-converted change fails only on the
        path nobody tested (ADR-487 D9's lesson, applied to a read).
        """
        return cls(
            id=row.id,
            employee_id=row.employee_id,
            type=row.type,
            message=row.message,
            is_read=row.is_read,
            created_at=row.created_at,
            dispatch_date=row.dispatch_date,
            expires_at=row.expires_at,
            # The SAME degrading resolution the SSE path uses. Calling
            # resolve_spec directly here would make one undeclared legacy row
            # 500 the whole list on REST while the stream rendered it fine.
            **spec_fields(row.type),
        )


def _channel_names(channels: Channel) -> list[str]:
    """`Channel` bitflags -> sorted lowercase names for the wire.

    A Flag is a Python construct; the clients get strings. Sorted so the list is
    stable across reads — an unordered list would make two identical responses
    compare unequal in a test or a cache key.

    `Channel.NONE` is zero, so it matches nothing in the iteration and yields
    `[]`, which is correct: no channel means nothing routes anywhere.
    """
    return sorted(c.name.lower() for c in Channel if c is not Channel.NONE and c in channels)


# What an unrecognised type renders as. See `_resolve_for_read`.
_UNKNOWN_FALLBACK = {
    "severity": Severity.INFO.value,
    "tone": Tone.NEUTRAL.value,
    "icon": "\U0001F514",     # bell
    # Banner, not ticker: an unrecognised row must not scroll past unseen when
    # nothing is known about whether it matters to the reader.
    "channels": ["banner"],
}


def _resolve_for_read(notification_type: str) -> dict:
    """Registry fields for a row being READ, degrading on an unknown type.

    `resolve_spec` REFUSES an undeclared type, and on the write path that is
    exactly right — it catches a typo'd or unregistered type at the call site,
    before a row exists that nothing can route.

    On a read the same refusal is a liability. The constructor guard was armed
    on 2026-10-05, so every row written since is declared; rows written BEFORE
    it carry whatever string their call site passed. One such row in a
    50-row page would raise out of the list comprehension and 500 the entire
    notification list — turning one unreadable row into no notifications at
    all, for a feature a walker uses to find out which truck they are on.

    So a read falls back: INFO, neutral, a bell, and the raw type as the label.
    Logged at warning because an unknown type reaching a read means either a
    pre-guard row (expected, finite) or a type raised through a path that
    bypassed the helpers (a defect worth seeing).

    Deliberately NOT a silent default. The registry refusing by default is the
    property ADR-487 D1 is built on; this is one narrow exemption on the read
    side, with the log line as its receipt.
    """
    try:
        spec = resolve_spec(notification_type)
    except Exception:
        logger.warning(
            "notification type %r is not in SPEC or RETIRED — rendering as INFO. "
            "Either a row predating the ADR-487 constructor guard, or a type "
            "raised without write_notification/fan_out.",
            notification_type,
        )
        return {**_UNKNOWN_FALLBACK, "label": notification_type}
    return {
        "severity": spec.severity.value,
        "label": spec.label,
        "tone": spec.tone.value,
        "icon": spec.icon,
        "channels": _channel_names(spec.channels),
    }


def spec_fields(notification_type: str) -> dict:
    """The four registry-resolved fields, as JSON-ready primitives.

    The single place both serialisation paths get them. `.value` on the enums
    because the SSE path hands its dict to `json.dumps`, which cannot serialise
    a StrEnum member on its own — and because the wire contract is the string,
    not Python's enum identity.
    """
    return _resolve_for_read(notification_type)
