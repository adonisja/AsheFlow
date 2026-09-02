"""Shared async HTTP client for all bot → AsheFlow API calls.

Handles:
- Cognito authentication (USER_PASSWORD_AUTH flow) to obtain a JWT
- Automatic token refresh when the token expires
- All API calls the dispatch cog needs
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import boto3
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)


class AsheFlowClient:
    """Async API client with automatic Cognito JWT management."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expiry: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._session: aiohttp.ClientSession | None = None
        self._path_prefix: str = ""

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the aiohttp session. Call once on bot startup."""
        from urllib.parse import urlparse
        parsed = urlparse(settings.api_base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self._path_prefix = parsed.path.rstrip("/")
        self._session = aiohttp.ClientSession(base_url=origin)
        try:
            await self._refresh_token()
        except ClientError as e:
            # Auth failure on startup (e.g. throttle cooldown, wrong password).
            # Log and continue — the bot's internal webhook server still starts.
            # Token will be retried lazily on the first API call.
            logger.warning("Startup Cognito auth failed (will retry on first API call): %s", e)

    async def close(self) -> None:
        """Close the aiohttp session. Call on bot shutdown."""
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        """Authenticate against Cognito and cache the IdToken.

        Cognito returns EITHER an ``AuthenticationResult`` OR a
        ``ChallengeName`` plus a ``Session`` — never both. This read the former
        unconditionally, so any challenge raised ``KeyError:
        'AuthenticationResult'``: no indication of what Cognito actually wanted,
        in a log nobody is watching, an hour after the change that caused it
        (ADR-362).

        A bot cannot answer a challenge. There is nobody to read a code out of an
        authenticator app, and a new password would have to be persisted
        somewhere it can find again. So the goal here is not to survive one —
        it is to say precisely what happened, because the fix is always
        operational.
        """
        try:
            client = boto3.client("cognito-idp", region_name=settings.aws_region)
            resp = client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": settings.bot_username,
                    "PASSWORD": settings.bot_password,
                },
                ClientId=settings.aws_cognito_client_id,
            )
        except ClientError as e:
            logger.error("Failed to authenticate bot with Cognito: %s", e)
            raise

        challenge = resp.get("ChallengeName")
        if challenge:
            # Named individually: "which challenge" determines who fixes it and
            # how, and a generic message sends someone reading it to the wrong
            # place.
            remedy = {
                "NEW_PASSWORD_REQUIRED": (
                    "the account is in FORCE_CHANGE_PASSWORD. Reset it with "
                    "admin-set-user-password --permanent."
                ),
                "SOFTWARE_TOKEN_MFA": (
                    "the account has TOTP enrolled. A bot cannot produce a code; "
                    "clear it with admin-set-user-mfa-preference."
                ),
                "EMAIL_OTP": (
                    "the account has email MFA enabled. A bot has no inbox; "
                    "clear it with admin-set-user-mfa-preference."
                ),
                "SELECT_MFA_TYPE": (
                    "the account has more than one MFA factor enrolled. Clear "
                    "them with admin-set-user-mfa-preference."
                ),
                "MFA_SETUP": (
                    "the pool requires MFA and the account has no factor. A bot "
                    "cannot enrol one — see docs/TODO-mfa-service-account.md."
                ),
            }.get(challenge, "this challenge has no automated path.")

            logger.error(
                "Bot Cognito sign-in was challenged with %s and cannot continue: %s "
                "Username=%s. Until this is cleared, every bot API call will fail.",
                challenge, remedy, settings.bot_username,
            )
            raise RuntimeError(
                f"Bot authentication requires {challenge}, which a service "
                f"account cannot satisfy. {remedy}"
            )

        result = resp.get("AuthenticationResult") or {}
        token = result.get("IdToken")
        if not token:
            # Neither branch. A response shape we do not know is worth saying
            # out loud rather than crashing on a subscript.
            logger.error(
                "Bot Cognito sign-in returned neither tokens nor a challenge; "
                "keys=%s", sorted(resp.keys()),
            )
            raise RuntimeError(
                "Bot authentication returned an unexpected response from Cognito."
            )

        self._token = token
        # IdToken expires in 1 hour; refresh 5 minutes early
        self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)
        logger.info("Bot Cognito token refreshed.")

    async def _ensure_token(self) -> str:
        if datetime.now(timezone.utc) >= self._token_expiry:
            await self._refresh_token()
        return self._token  # type: ignore[return-value]

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def get_dispatch(self, date: str) -> dict[str, Any]:
        """Fetch the full dispatch for a given date (YYYY-MM-DD)."""
        token = await self._ensure_token()
        async with self._session.get(f"{self._path_prefix}/dispatch/{date}", headers=self._headers(token)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_trucks(self) -> list[dict[str, Any]]:
        """Fetch all active trucks (for name lookups)."""
        token = await self._ensure_token()
        async with self._session.get(f"{self._path_prefix}/trucks/", headers=self._headers(token)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post_confirmation(self, date: str, employee_id: str, status: str) -> dict[str, Any]:
        """Record a confirmation response (confirmed | declined) for an employee."""
        token = await self._ensure_token()
        payload = {"employee_id": employee_id, "status": status}
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/confirmations",
            json=payload,
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def record_crew_embed(self, date: str, truck_id: str, message_id: int) -> dict[str, Any]:
        """Report the Discord message id of a truck's crew embed (ADR-295 D2).

        Lets a later crew change EDIT that message rather than leaving a stale
        roster in the channel with a correction posted beside it.
        """
        token = await self._ensure_token()
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/trucks/{truck_id}/crew-embed",
            json={"message_id": message_id},
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def record_day_summary(self, date: str, channel: str, message_id: int) -> dict[str, Any]:
        """Report the id of a DAY-level summary post (ADR-327 D2).

        `channel` is "drivers" or "trainers". message_id 0 clears the receipt,
        used when a fetch finds the message was deleted in Discord — same
        sentinel as record_crew_embed.
        """
        token = await self._ensure_token()
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/day-summary",
            json={"channel": channel, "message_id": message_id},
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_day_summary(self, date: str) -> dict[str, Any]:
        """Fetch the standing day-summary message ids, if any (ADR-327 D2)."""
        token = await self._ensure_token()
        async with self._session.get(
            f"{self._path_prefix}/dispatch/{date}/day-summary",
            headers=self._headers(token),
        ) as resp:
            if resp.status == 404:
                return {}
            resp.raise_for_status()
            return await resp.json()

    async def get_confirmations(self, date: str) -> dict:
        """Fetch all confirmation statuses for a given dispatch date.

        Returns the full response body: { "date": ..., "confirmations": { employee_id: status } }
        """
        token = await self._ensure_token()
        async with self._session.get(
            f"{self._path_prefix}/dispatch/{date}/confirmations", headers=self._headers(token)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def publish_dispatch(self, date: str) -> dict[str, Any]:
        """Mark a dispatch as published (sets published_at on the backend)."""
        token = await self._ensure_token()
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/publish", headers=self._headers(token)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_employee_by_discord(self, discord_id: str) -> dict[str, Any] | None:
        """Look up an employee record by Discord ID. Returns None if not found."""
        token = await self._ensure_token()
        try:
            async with self._session.get(
                f"{self._path_prefix}/employees/by-discord/{discord_id}",
                headers=self._headers(token),
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.warning("Could not fetch employee for discord_id %s: %s", discord_id, e)
            return None

    async def get_trainee_current_phase(self, trainee_id: str) -> int | None:
        """Return the current training phase number for a trainee (1–4), or None if no record."""
        token = await self._ensure_token()
        try:
            async with self._session.get(
                f"{self._path_prefix}/training/trainee/{trainee_id}",
                headers=self._headers(token),
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                records = await resp.json()
                if not records:
                    return 1  # No records yet → Phase 1 on next dispatch
                # Most recent record (last in list or highest day_number)
                latest = max(records, key=lambda r: r.get("current_day_number", 0))
                return latest.get("current_day_number", 1)
        except Exception as e:
            logger.warning("Could not fetch training phase for %s: %s", trainee_id, e)
            return None


# Singleton — imported by cogs
api = AsheFlowClient()
