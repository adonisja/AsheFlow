"""Shared async HTTP client for all bot → AsheFlow API calls.

Handles:
- Cognito authentication (OAuth2 client_credentials, ADR-363) to obtain a JWT
- Automatic token refresh when the token expires
- All API calls the dispatch cog needs
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)


class AsheFlowClient:
    """Async API client with automatic Cognito JWT management."""

    def __init__(self) -> None:
        # ADR-441 D2. ONE TOKEN PER COMPANY.
        #
        # This was a single `self._token` shared by every request, while the bot
        # already resolved company_id per Discord guild. With one active tenant
        # that worked; with two, company B's command either gets refused (its
        # token carries A's tenant scope) or is authorised against COMPANY A's
        # DATA — the cross-tenant write ADR-364 exists to prevent.
        #
        # Key `None` is the env-credential fallback (D3): local development runs
        # one company and should not need the round trip.
        self._tokens: dict[str | None, str] = {}
        self._expiry: dict[str | None, datetime] = {}
        self._creds: dict[str, tuple[str, str]] = {}
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
        # ADR-441. NO TOKEN IS FETCHED HERE ANY MORE. There is no longer "the"
        # token to warm: each company gets its own on first use, and which
        # companies this process will serve is not known until a command
        # arrives. Pre-fetching one would mean picking a tenant arbitrarily,
        # which is the bug this change removes.

    async def close(self) -> None:
        """Close the aiohttp session. Call on bot shutdown."""
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _credentials_for(self, company_id: str | None) -> tuple[str, str]:
        """This tenant's Cognito client id and secret (ADR-441 D1).

        Fetched from the backend's internal channel — the same one the bot
        already uses for guild config, authenticated with X-Internal-Secret.
        NOT the super-admin reveal endpoint: that would need a token which can
        read every tenant's secret and do everything else a super admin can.

        Cached per company for the process lifetime. A rotation therefore needs
        a bot restart, which is the same as today and is acceptable: rotation is
        a deliberate act, and a bot that re-fetched on every 401 would hammer
        the endpoint during an outage.

        Falls back to the env credential only when the backend reports the
        company HAS NO client (404), never when the fetch fails. A failed fetch
        with a working fallback is exactly how a request ends up authorised
        against the wrong tenant.
        """
        if company_id is None:
            return self._env_credentials()

        cached = self._creds.get(company_id)
        if cached:
            return cached

        base = os.environ.get("API_BASE_URL", "http://backend:8000/api/v1")
        secret = os.environ.get("INTERNAL_SECRET", "")
        url = f"{base.rstrip('/')}/internal/machine-credentials/{company_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 404:
                    # No client provisioned for this company. Env fallback is
                    # correct here and only here.
                    logger.info(
                        "No machine client for company %s; using env credentials.",
                        company_id,
                    )
                    return self._env_credentials()
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Could not fetch machine credentials for {company_id}: "
                        f"{resp.status} {body[:120]}"
                    )
                data = await resp.json()

        pair = (data["client_id"], data["client_secret"])
        self._creds[company_id] = pair
        return pair

    @staticmethod
    def _env_credentials() -> tuple[str, str]:
        """The single-tenant fallback (ADR-441 D3)."""
        if not (settings.cognito_m2m_client_id and settings.cognito_m2m_client_secret):
            raise RuntimeError(
                "COGNITO_M2M_CLIENT_ID and COGNITO_M2M_CLIENT_SECRET are required. "
                "The BOT_USERNAME/BOT_PASSWORD fallback was removed in ADR-377: a "
                "user account cannot answer an MFA challenge, so it could not have "
                "worked once enforcement lands."
            )
        return (settings.cognito_m2m_client_id, settings.cognito_m2m_client_secret)

    async def _refresh_token(self, company_id: str | None = None) -> None:
        """Obtain an API token and cache it until shortly before it expires.

        One path. ADR-363 kept a USER_PASSWORD_AUTH fallback so a rollback was
        an env change rather than a deploy; ADR-377 removed it, because MFA
        enforcement makes it a rollback that provably cannot work. A bot has no
        phone and cannot answer a challenge, so under MfaConfiguration=ON the
        `asheflow.bot` user account is refused at sign-in. Keeping the branch
        would leave a safety net that looks like one and is not.

        Rolling back the machine identity is now a git revert.
        """
        await self._refresh_token_m2m(company_id)

    async def _refresh_token_m2m(self, company_id: str | None = None) -> None:
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
        # ADR-441 — this tenant's credential, not "the" credential.
        client_id, client_secret = await self._credentials_for(company_id)

        domain = (settings.cognito_oauth_domain or "").rstrip("/")
        if not domain:
            raise RuntimeError(
                "COGNITO_OAUTH_DOMAIN is not set; the machine identity needs the "
                "user pool token endpoint."
            )
        if not domain.startswith("http"):
            domain = f"https://{domain}"

        auth = aiohttp.BasicAuth(client_id, client_secret)
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
            self._tokens[company_id] = token
            self._expiry[company_id] = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in - margin
            )
            logger.info(
                "Bot M2M token acquired for company=%s (expires in %ss).",
                company_id or "env", expires_in,
            )

    async def _ensure_token(self, company_id: str | None = None) -> str:
        """A live token for THIS company (ADR-441 D2).

        Each tenant's token expires on its own hour, so the expiry check is per
        key rather than one shared deadline. A company with no cached expiry
        reads as already expired, which fetches on first use.
        """
        stale = self._expiry.get(company_id, datetime.min.replace(tzinfo=timezone.utc))
        if datetime.now(timezone.utc) >= stale:
            await self._refresh_token(company_id)
        return self._tokens[company_id]

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def get_dispatch(self, date: str, *, company_id: str) -> dict[str, Any]:
        """Fetch the full dispatch for a given date (YYYY-MM-DD)."""
        token = await self._ensure_token(company_id)
        async with self._session.get(f"{self._path_prefix}/dispatch/{date}", headers=self._headers(token)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_trucks(self, *, company_id: str) -> list[dict[str, Any]]:
        """Fetch all active trucks (for name lookups)."""
        token = await self._ensure_token(company_id)
        async with self._session.get(f"{self._path_prefix}/trucks/", headers=self._headers(token)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post_confirmation(self, date: str, employee_id: str, status: str, *, company_id: str) -> dict[str, Any]:
        """Record a confirmation response (confirmed | declined) for an employee."""
        token = await self._ensure_token(company_id)
        payload = {"employee_id": employee_id, "status": status}
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/confirmations",
            json=payload,
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def record_crew_embed(self, date: str, truck_id: str, message_id: int, *, company_id: str) -> dict[str, Any]:
        """Report the Discord message id of a truck's crew embed (ADR-295 D2).

        Lets a later crew change EDIT that message rather than leaving a stale
        roster in the channel with a correction posted beside it.
        """
        token = await self._ensure_token(company_id)
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/trucks/{truck_id}/crew-embed",
            json={"message_id": message_id},
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def record_day_summary(self, date: str, channel: str, message_id: int, *, company_id: str) -> dict[str, Any]:
        """Report the id of a DAY-level summary post (ADR-327 D2).

        `channel` is "drivers" or "trainers". message_id 0 clears the receipt,
        used when a fetch finds the message was deleted in Discord — same
        sentinel as record_crew_embed.
        """
        token = await self._ensure_token(company_id)
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/day-summary",
            json={"channel": channel, "message_id": message_id},
            headers=self._headers(token),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_day_summary(self, date: str, *, company_id: str) -> dict[str, Any]:
        """Fetch the standing day-summary message ids, if any (ADR-327 D2)."""
        token = await self._ensure_token(company_id)
        async with self._session.get(
            f"{self._path_prefix}/dispatch/{date}/day-summary",
            headers=self._headers(token),
        ) as resp:
            if resp.status == 404:
                return {}
            resp.raise_for_status()
            return await resp.json()

    async def get_confirmations(self, date: str, *, company_id: str) -> dict:
        """Fetch all confirmation statuses for a given dispatch date.

        Returns the full response body: { "date": ..., "confirmations": { employee_id: status } }
        """
        token = await self._ensure_token(company_id)
        async with self._session.get(
            f"{self._path_prefix}/dispatch/{date}/confirmations", headers=self._headers(token)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def publish_dispatch(self, date: str, *, company_id: str) -> dict[str, Any]:
        """Mark a dispatch as published (sets published_at on the backend)."""
        token = await self._ensure_token(company_id)
        async with self._session.post(
            f"{self._path_prefix}/dispatch/{date}/publish", headers=self._headers(token)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_employee_by_discord(self, discord_id: str, *, company_id: str) -> dict[str, Any] | None:
        """Look up an employee record by Discord ID. Returns None if not found."""
        token = await self._ensure_token(company_id)
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

    async def get_trainee_current_phase(self, trainee_id: str, *, company_id: str) -> int | None:
        """Return the current training phase number for a trainee (1–4), or None if no record."""
        token = await self._ensure_token(company_id)
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
