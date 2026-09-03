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
        """Obtain an API token and cache it until shortly before it expires.

        Two paths. The machine identity (ADR-363) is preferred and is the one
        that survives MFA enforcement; the password path is the pre-migration
        fallback, kept so a rollback is an env change rather than a deploy.
        """
        if settings.cognito_m2m_client_id and settings.cognito_m2m_client_secret:
            await self._refresh_token_m2m()
        else:
            await self._refresh_token_password()

    async def _refresh_token_m2m(self) -> None:
        """OAuth2 client_credentials against the user pool token endpoint.

        No refresh token exists in this flow — verified against a real token,
        the response is exactly {access_token, expires_in, token_type}. So there
        is nothing to persist and nothing to rotate: when the token expires the
        bot asks for another. That is simpler than the password path it
        replaces, and it cannot be challenged.

        `expires_in` is honoured rather than assumed. The app client is
        configured for one hour, but reading the response means a console change
        to that setting does not silently strand the bot on a stale token.
        """
        domain = (settings.cognito_oauth_domain or "").rstrip("/")
        if not domain:
            raise RuntimeError(
                "COGNITO_OAUTH_DOMAIN is not set; the machine identity needs the "
                "user pool token endpoint."
            )
        if not domain.startswith("http"):
            domain = f"https://{domain}"

        auth = aiohttp.BasicAuth(
            settings.cognito_m2m_client_id,
            settings.cognito_m2m_client_secret,
        )
        # Its own session, not self._session: that one is bound to the API's
        # base_url and cannot reach the Cognito domain. Short-lived, because
        # this runs once an hour.
        async with aiohttp.ClientSession() as session, session.post(
            f"{domain}/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                # The token endpoint reports failures as an OAuth error code,
                # not an exception. invalid_client is the one worth naming: it
                # means the secret is wrong or rotated, which is operational.
                err = body.get("error", "unknown_error")
                logger.error(
                    "Bot M2M token request failed (%s): %s. client_id=%s",
                    resp.status, err, settings.cognito_m2m_client_id,
                )
                raise RuntimeError(f"Bot machine authentication failed: {err}")

            token = body.get("access_token")
            if not token:
                logger.error(
                    "Bot M2M token response carried no access_token; keys=%s",
                    sorted(body.keys()),
                )
                raise RuntimeError("Bot machine authentication returned no token.")

            expires_in = int(body.get("expires_in", 3600))
            # Refresh 5 minutes early, and never schedule a refresh in the past
            # if someone configures a very short token.
            margin = min(300, max(30, expires_in // 12))
            self._token = token
            self._token_expiry = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in - margin
            )
            logger.info("Bot M2M token acquired (expires in %ss).", expires_in)

    async def _refresh_token_password(self) -> None:
        """Authenticate as a Cognito USER and cache the IdToken.

        Superseded by the machine identity (ADR-363) and kept only for rollback.
        A user account cannot answer an MFA challenge, which is exactly why this
        path blocks enforcement — see the challenge handling below, which makes
        that legible instead of a KeyError.
        """
        if not (settings.bot_username and settings.bot_password):
            raise RuntimeError(
                "No bot credentials configured: set COGNITO_M2M_CLIENT_ID and "
                "COGNITO_M2M_CLIENT_SECRET (preferred), or BOT_USERNAME and "
                "BOT_PASSWORD."
            )
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
            remedy = {
                "NEW_PASSWORD_REQUIRED": (
                    "the account is in FORCE_CHANGE_PASSWORD. Reset it with "
                    "admin-set-user-password --permanent."
                ),
                "SOFTWARE_TOKEN_MFA": (
                    "the account has TOTP enrolled. A bot cannot produce a code; "
                    "migrate to the machine identity (ADR-363)."
                ),
                "EMAIL_OTP": (
                    "the account has email MFA enabled. A bot has no inbox; "
                    "migrate to the machine identity (ADR-363)."
                ),
                "SELECT_MFA_TYPE": (
                    "the account has more than one MFA factor enrolled. Migrate "
                    "to the machine identity (ADR-363)."
                ),
                "MFA_SETUP": (
                    "the pool requires MFA and the account has no factor. A bot "
                    "cannot enrol one; migrate to the machine identity (ADR-363)."
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
