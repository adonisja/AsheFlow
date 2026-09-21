"""The OAuth link that puts the bot in a company's Discord server (ADR-448).

WHY THIS EXISTS. Company Settings asks a tenant admin for a Server ID and
fourteen channel and role ids. Every one can be correct and Discord will still
do nothing, because the bot is not a member of that server — `bot.get_guild()`
reads the bot's own list of joined servers, and only a server administrator can
authorise it through Discord's consent screen.

Until this module, that step existed nowhere in the product: no page, no email,
no link. It failed as `DiscordInviteError("bot", "Check Discord settings")`,
which is accurate about the stage and actively misleading about the remedy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5

# `bot` to join the server, `applications.commands` for the slash commands the
# cogs register. Anything less and /setup silently does not appear.
_SCOPES = "bot applications.commands"

# Administrator. Matches how staging has run since May, and the bot's own
# actions span channel creation, invites, role assignment and member
# moderation — an under-scoped invite fails later, in pieces, at dispatch time.
# Narrowing this is a deliberate change with its own testing, not a default.
_PERMISSIONS = "8"


@dataclass(frozen=True)
class BotGuildStatus:
    """What the bot knows about a company's server.

    `in_guild` is THREE-STATE on purpose: True, False, or None for "could not
    ask". A deploy restarting the bot must not put a red cross next to a
    correct configuration — "we could not check" and "it is not there" are
    different facts and the UI says so differently.
    """
    invite_url: Optional[str]
    in_guild: Optional[bool]
    ready: bool


def _bot_url() -> str:
    return settings.bot_internal_url.rstrip("/")


def get_status(guild_id: int | None) -> BotGuildStatus:
    """Ask the running bot for its application id and guild membership.

    Never raises. Every failure degrades to "could not ask" — this feeds a
    settings page, and a page that 500s because the bot is restarting is worse
    than one that says it could not check.
    """
    try:
        resp = requests.get(
            f"{_bot_url()}/internal/guild-status",
            params={"guild_id": str(guild_id)} if guild_id else None,
            headers={"X-Internal-Secret": settings.internal_secret},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Could not reach the bot for guild status: %s", exc)
        return BotGuildStatus(invite_url=None, in_guild=None, ready=False)

    app_id = data.get("application_id")
    return BotGuildStatus(
        # Built from the RUNNING bot's application id, never a constant: staging
        # and prod are different Discord applications, and a hardcoded id would
        # send prod admins to invite the staging bot.
        invite_url=build_invite_url(app_id) if app_id else None,
        in_guild=data.get("in_guild"),
        ready=bool(data.get("ready")),
    )


def build_invite_url(application_id: str) -> str:
    """The Discord consent URL. Public by construction — a client id is not a secret."""
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={application_id}"
        f"&permissions={_PERMISSIONS}"
        f"&scope={_SCOPES.replace(' ', '%20')}"
    )
