"""Discord sends as bounded, retried, recorded tasks (ADR-487 D7).

WHAT THIS REPLACES
==================

Eleven sites did this, each slightly differently:

    def _fire_discord_dm(discord_id: str, message: str) -> None:
        def _run():
            try:
                http_requests.post(f"{bot_url}/internal/dm", json={...},
                                   headers={...}, timeout=5)
            except Exception as exc:
                logger.warning("promote DM failed for %s: %s", discord_id, exc)
        threading.Thread(target=_run, daemon=True).start()

Three defects, in increasing order of severity.

**Unbounded concurrency.** One thread per send, started from a request handler.
A bulk onboarding of 80 employees starts 80 threads against a rate-limited API,
and `daemon=True` means a container stopping mid-flight drops every one
silently. The task modules already knew better — `enrich_manifest.py` uses
`ThreadPoolExecutor(max_workers=_GEOCLIENT_WORKERS)` — the idea just never
reached the request path.

**No retry.** A transient 502 from the bot is a logged warning and a message
nobody receives. Celery's retry state lives in the broker and survives a worker
restart; a thread's does not.

**The response was never checked — on ten of the eleven.** Measured by walking
the AST for `raise_for_status`, `.status_code`, `resp.ok` or `if resp` in each:

    bot-calling threads whose POST is inline:  10
      ...checking the response:                 0

So a dead bot and a working bot produced identical logs as long as the socket
opened. That is strictly worse than the thread count: unbounded threads are a
capacity problem that shows up under load, and this is a correctness problem
that shows up never. The eleventh, `discord_invite.py`, raises
`DiscordInviteError` with a `stage` — the only Discord send in the codebase with
any error discipline, and ADR-443 had to build it a resend endpoint anyway
because even a raised failure left no durable record.

WHY A STATUS IS NOT JUST A FAILURE
==================================

`autoretry_for=(RequestException,)` deliberately does NOT include the
`HTTPError` that `raise_for_status()` would raise. "The request failed" and "the
request was refused" need different answers, and retrying a refusal five times
delays the alert to the only person who can fix it:

    timeout / connection / 5xx      retry with backoff
    429 + Retry-After               honour the header, not the curve
    404 recipient not in the guild  stop, record
    403 token revoked               stop, record, AND alert the super admin
    400 malformed payload           stop, record — it will fail identically

That distinction is the LEARNING_GUIDE's "route a failure by who owns the
credential, not by whether it crossed the network".

DISCORD IS STILL SECONDARY
==========================

ADR-324 settled that Discord is a convenience surface, not the channel of
record: finalize continues when it is down. This makes the secondary channel
reliable and observable; it does not promote it. A send that exhausts its
retries leaves the in-app notification intact and the operation complete, which
is what D3's after-commit ordering already guarantees.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from app.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# The bot's internal endpoints, as a closed set. A typo in a `kind` string would
# otherwise produce a 404 that looks exactly like "recipient not in the guild".
KINDS: frozenset[str] = frozenset({
    "dm",                  # a direct message to one member
    "swap",                # a truck reassignment, posted to both channels
    "crew-embed-update",   # refresh a posted crew card
    "revoke-member",       # remove channel access
    "role-sync",           # reconcile a member's Discord roles
    "invite",              # fetch an invite link for a new employee
})

# Terminal statuses, and what each means. A status NOT in here is retried.
_TERMINAL: dict[int, str] = {
    400: "bad_request",        # the payload is wrong; identical retries fail
    403: "forbidden",          # the bot token is revoked or lacks the permission
    404: "recipient_missing",  # the member is not in the guild
    410: "gone",
}

_TIMEOUT_SECONDS = 10


class DiscordRefused(RuntimeError):
    """A response that must NOT be retried. Carries the classification."""

    def __init__(self, status: int, reason: str):
        super().__init__(f"discord refused: {status} {reason}")
        self.status = status
        self.reason = reason


@celery_app.task(
    name="app.tasks.discord_delivery.send_discord",
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=2,          # 2s, 4s, 8s, 16s, 32s
    retry_backoff_max=300,
    retry_jitter=True,        # see below — this is not optional here
    max_retries=5,
    acks_late=True,           # a killed worker re-queues rather than loses it
)
def send_discord(
    self,
    kind: str,
    payload: dict[str, Any],
    *,
    notification_id: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """POST one message to the bot, with the retry policy and a classified result.

    `retry_jitter` matters here specifically rather than as a default: 51 of the
    original notification sites were fan-outs, so one event produces N sends.
    Without jitter every one fails at the same instant and retries at the same
    instant — `retry_backoff` alone converts a fan-out into a synchronised
    thundering herd against a rate-limited API, which is how a transient failure
    becomes a sustained one.

    `notification_id` is optional because not every Discord send has a
    notification behind it: the role syncs and channel revokes are access
    changes. Those record an audit entry on terminal failure instead, because a
    silently-failed revoke is a security finding rather than an inconvenience.
    """
    if kind not in KINDS:
        # Not retried: a bad kind is a programming error, and five attempts
        # would just delay the traceback.
        raise ValueError(
            f"unknown Discord endpoint {kind!r}; expected one of "
            f"{sorted(KINDS)} (ADR-487 D7)"
        )

    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret = os.environ.get("INTERNAL_SECRET", "")

    resp = requests.post(
        f"{bot_url}/internal/{kind}",
        json=payload,
        headers={"X-Internal-Secret": secret},
        timeout=_TIMEOUT_SECONDS,
    )

    # 429 first: the server told us when to come back, so honour that rather
    # than the backoff curve, which knows nothing about the rate limit window.
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp)
        logger.info("discord rate-limited on %s, retrying in %ss", kind, retry_after)
        raise self.retry(countdown=retry_after)

    if resp.status_code in _TERMINAL:
        reason = _TERMINAL[resp.status_code]
        _record_terminal_failure(notification_id, reason)
        if resp.status_code == 403:
            # Only a super admin can rotate the token, and they have no Employee
            # row so a Notification cannot reach them (ADR-324 D2).
            _alert_platform(company_id, reason)
        logger.warning("discord %s refused for %s: %s", resp.status_code, kind, reason)
        return {"status": "refused", "code": resp.status_code, "reason": reason}

    if resp.status_code >= 500:
        # Retried by autoretry_for via RequestException.
        resp.raise_for_status()

    _mark_delivered(notification_id)
    return {"status": "sent", "code": resp.status_code}


def _parse_retry_after(resp: requests.Response) -> int:
    """Seconds from a Retry-After header, bounded.

    Discord sends it as seconds; a missing or unparseable value falls back to a
    short wait rather than to zero, which would hammer the limit that just
    fired. Capped so a hostile or buggy value cannot park a task for a day.
    """
    raw = resp.headers.get("Retry-After", "")
    try:
        seconds = int(float(raw))
    except (TypeError, ValueError):
        return 5
    return max(1, min(seconds, 300))


def _mark_delivered(notification_id: str | None) -> None:
    """Stamp dispatched_at. Best effort: the send already happened.

    Raising here would retry a send that SUCCEEDED, which is worse than losing
    the stamp — the sweep's job is to find rows with no stamp, and a duplicate
    send is a message a person reads twice.
    """
    if notification_id is None:
        return
    db = SessionLocal()
    try:
        from app.models.notification import Notification

        db.query(Notification).filter(
            Notification.id == notification_id,
        ).update({"dispatched_at": datetime.now(timezone.utc)},
                 synchronize_session=False)
        db.commit()
    except Exception:
        logger.warning("could not stamp dispatched_at for %s", notification_id,
                       exc_info=True)
        db.rollback()
    finally:
        db.close()


def _record_terminal_failure(notification_id: str | None, reason: str) -> None:
    """Record that this will never be delivered.

    ADR-443 exists because a swallowed Discord failure left an employee who was
    `active`, looked entirely normal, and was simply absent from Discord — with
    no record the send was attempted. A terminal failure has to be visible
    somewhere a person looks.

    `reason` is a short classification, never the response body: Dimension 6.
    """
    if notification_id is None:
        return
    db = SessionLocal()
    try:
        from app.models.notification import Notification

        db.query(Notification).filter(
            Notification.id == notification_id,
        ).update(
            {
                "delivery_failed_at": datetime.now(timezone.utc),
                "delivery_error": f"discord:{reason}"[:80],
            },
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        logger.warning("could not record delivery failure for %s", notification_id,
                       exc_info=True)
        db.rollback()
    finally:
        db.close()


def _alert_platform(company_id: str | None, reason: str) -> None:
    """A revoked token is platform infrastructure, not a tenant problem.

    Routed to `raise_platform_alert` rather than a Notification because a super
    admin has no Employee row (ADR-324 D2) — and because the tenant's admins
    cannot rotate a bot token however clearly they are told about it.
    """
    db = SessionLocal()
    try:
        from app.services.integration_alerts import (
            DISCORD_INTEGRATION_FAILED,
            raise_platform_alert,
        )

        raise_platform_alert(
            db,
            alert_type=DISCORD_INTEGRATION_FAILED,
            company_id=company_id,
            message=(
                "Discord refused a send with 403 — the bot token is revoked or "
                "lacks the required permission. Crews are on in-app "
                "notifications until it is rotated."
            ),
            severity="warning",
        )
    except Exception:
        logger.warning("could not raise the platform alert for a 403", exc_info=True)
    finally:
        db.close()
