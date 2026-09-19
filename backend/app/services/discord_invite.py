"""Fetch a Discord guild invite from the bot and email it (ADR-443).

Two callers, deliberately sharing one implementation:

  * first login (`deps.get_caller_employee`) — fire-and-forget on a thread,
    because a sign-in must not wait on Discord or SES.
  * the resend endpoint — inline, because an operator pressed a button and is
    looking at the result.

They differ only in whether they wait and whether they report. Splitting them
into two implementations would mean the one nobody exercises by hand drifts,
and that one is the login path.

THE URL IS NOT OURS TO KEEP. The bot mints it per request and Discord links can
expire or be revoked, so nothing here persists one. A stored URL replayed later
hands out a link that may be dead, which is worse than not sending because it
looks like it worked.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import requests
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.email import send_discord_invite_email

logger = logging.getLogger(__name__)


class DiscordInviteError(RuntimeError):
    """A step failed, named so the caller can say which.

    `stage` is the remedy, not just the symptom: "bot" sends an operator to
    Discord configuration, "email" to the address or the SES sandbox. A single
    opaque failure would send them to both.
    """

    def __init__(self, stage: str, detail: str):
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class InviteResult:
    invite_url: str
    email: str


def fetch_and_send(employee) -> InviteResult:
    """Ask the bot for an invite, then email it. Raises DiscordInviteError.

    Synchronous. `send_on_first_login` wraps this for the path that must not
    block.
    """
    if not employee.email:
        raise DiscordInviteError("email", "No email address on file for this employee.")

    try:
        resp = requests.post(
            f"{settings.bot_internal_url}/internal/invite",
            json={"name": employee.name, "company_id": str(employee.company_id)},
            headers={"X-Internal-Secret": settings.internal_secret},
            timeout=10,
        )
        resp.raise_for_status()
        invite_url = resp.json().get("invite_url")
    except Exception as exc:
        # The bot is a separate process that may be down, misconfigured, or
        # pointed at a guild it cannot create invites for. Naming the stage is
        # what stops an operator checking email settings for a Discord problem.
        logger.warning("Discord invite bot call failed for %s: %s", employee.name, exc)
        raise DiscordInviteError(
            "bot", "The bot could not provide an invite link. Check Discord settings."
        ) from exc

    if not invite_url:
        logger.error("Bot returned no invite_url for %s.", employee.name)
        raise DiscordInviteError(
            "bot", "The bot returned no invite link. Check the invite channel setting."
        )

    try:
        send_discord_invite_email(
            to_email=employee.email,
            employee_name=employee.name,
            invite_url=invite_url,
        )
    except ClientError as exc:
        # _log_ses_failure (ADR-442 D3) has already logged this with the
        # sandbox hint where it applies; the code is re-surfaced so the caller
        # can put it in front of the operator.
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise DiscordInviteError(
            "email", f"The invite email could not be delivered ({code})."
        ) from exc

    return InviteResult(invite_url=invite_url, email=employee.email)


def send_on_first_login(employee) -> None:
    """Best effort, non-blocking — the original first-login behaviour.

    Every failure is swallowed here and that is correct: nobody is waiting on
    this thread, and an exception raised in it cannot reach the request that
    started it.

    It is also why ADR-443 exists. A silent failure leaves an employee who is
    `active`, looks entirely normal, and is simply absent from Discord — with
    no record that the send was ever attempted. The resend endpoint is the
    second chance this path cannot give itself.
    """
    def _fire() -> None:
        try:
            fetch_and_send(employee)
        except DiscordInviteError as exc:
            logger.warning(
                "Discord invite (%s) failed for %s: %s",
                exc.stage, employee.name, exc.detail,
            )

    threading.Thread(target=_fire, daemon=True).start()
