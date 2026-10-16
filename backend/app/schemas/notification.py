from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict

import logging

from app.services.notification_spec import Channel, Severity, Tone, link_for, resolve_spec

logger = logging.getLogger(__name__)


class NotificationLinkOut(BaseModel):
    """Where a notification opens (ADR-519)."""
    route: str
    kind: Optional[str] = None
    id: Optional[str] = None
    date: Optional[str] = None


class NotificationActionOut(BaseModel):
    """One control a notification carries (ADR-494).

    A RESPONSE model, so the Dimension 9 rule about `Any` at the trust boundary
    does not apply — nothing here is client-supplied. The shape mirrors
    `notification_spec.NotificationAction` exactly; it is restated rather than
    reused because that one is a frozen dataclass in a module with no Pydantic
    dependency, and importing a schema there would invert the layering.
    """

    label: str
    route: str
    style: str = "default"

    model_config = ConfigDict(from_attributes=True)


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

    # ADR-494. The controls a PROMPT or GATE carries, resolved from the registry
    # per read like `channels` is. Empty for the 80 types that declare none, so
    # a client that ignores it sees exactly what it saw before.
    #
    # A list of objects rather than a single `redirect_to` string: ADR-494 D10
    # approved two controls on some types, and a bare route cannot carry the
    # label or the style. The `style` is a semantic role ("primary", "danger"),
    # never a colour — the surfaces own different palettes.
    actions: list[NotificationActionOut] = []

    # ADR-519: where tapping it goes, resolved per read like `channels`.
    # `route` has any `{id}` filled; `kind` and `id` let a screen focus the item;
    # `date` is the row's dispatch_date. Always present (never None) so both
    # transports carry the same keys.
    link: "NotificationLinkOut"

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
            #
            # `row` is passed so ADR-494 D6's gate check can run. No session is
            # available here — this is a classmethod on a schema — so only the
            # checks that need no query apply (expiry), and the rest fail safe
            # to a prompt. `from_row_scoped` is the session-aware entry point
            # that routers use; this one stays for callers that have no db.
            **spec_fields(row.type, row=row),
        )

    @classmethod
    def from_row_scoped(cls, row, db) -> "NotificationResponse":
        """`from_row` with a session, so every ADR-494 D6 check can run.

        Two constructors rather than a default `db=None` on one, because the
        difference is not a detail a caller should be able to miss: without a
        session a gate degrades to a prompt, and a router that MEANT to verify
        the gate would silently get the weaker answer. A separate name makes the
        session a visible decision at the call site.
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
            **spec_fields(row.type, row=row, db=db),
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


from app.services.notification_degrade import degrade_channels, drop_if_settled


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
    out = {
        "severity": spec.severity.value,
        "label": spec.label,
        "tone": spec.tone.value,
        "icon": spec.icon,
        "channels": _channel_names(spec.channels),
    }
    # ADR-494: a PROMPT or GATE must name where the reader goes, so the controls
    # travel with the notification rather than being a per-type `switch` in each
    # client.
    #
    # ALWAYS present, `[]` for the 80 types that declare none. The first draft
    # emitted it only when non-empty, which ADR-487 D4's contract test caught:
    # `test_a_declared_type_resolves` asserts every type resolves to the SAME
    # field set, because a key that appears per-type is a key the hand-built SSE
    # dict and the Pydantic model can disagree about — the two-transport drift
    # that file exists to prevent. A conditional key also makes the client write
    # `n.actions?.map` on one transport and `n.actions.map` on the other.
    out["actions"] = [
        {"label": a.label, "route": a.route, "style": a.style}
        for a in spec.actions
    ]
    return out


def spec_fields(notification_type: str, row=None, db=None) -> dict:
    """The registry-resolved fields, as JSON-ready primitives.

    The single place both serialisation paths get them. `.value` on the enums
    because the SSE path hands its dict to `json.dumps`, which cannot serialise
    a StrEnum member on its own — and because the wire contract is the string,
    not Python's enum identity.

    `row` and `db` are what ADR-494 D6 added: the server decides when a GATE
    cannot be honoured and omits it, so neither client implements a downgrade
    rule and they cannot disagree about one. Both are optional and the omission
    fails SAFE — without them an unverifiable gate degrades to a prompt rather
    than walling someone.

    `actions` is included only when the type declares them, so the 80 types
    that carry none keep their payload unchanged.
    """
    fields = _resolve_for_read(notification_type)

    if row is not None:
        fields["channels"] = degrade_channels(db, row, fields["channels"])
        # ADR-505 D2: a notification with a final answer stops interrupting.
        # After degrade_channels, so a degraded gate (now a prompt) is settled too.
        fields["channels"] = drop_if_settled(db, row, fields["channels"])

    fields["link"] = resolve_link(notification_type, row)
    return fields


def resolve_link(notification_type: str, row=None) -> dict:
    """ADR-519: the registry's Link for this type, with the row's reference.

    A templated route (`/help-requests/{id}`) needs the id; a row written before
    ADR-519 has none, so it opens the link's fallback page instead of a broken
    path. A kind with no id still opens its page; the client simply has nothing
    to focus.
    """
    link = link_for(notification_type)
    target_id = getattr(row, "target_id", None) if row is not None else None
    d = getattr(row, "dispatch_date", None) if row is not None else None
    route = link.route
    if "{id}" in route:
        route = route.replace("{id}", target_id) if target_id else (link.fallback or "/notifications")
    return {
        "route": route,
        "kind": link.kind,
        "id": target_id if link.kind else None,
        "date": d.isoformat() if d is not None else None,
    }
