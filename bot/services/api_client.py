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
        # aiohttp base_url only accepts an origin (scheme+host+port), no path.
        # We split the configured URL and prepend the path prefix on each call.
        from urllib.parse import urlparse
        parsed = urlparse(settings.api_base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self._path_prefix = parsed.path.rstrip("/")
        self._session = aiohttp.ClientSession(base_url=origin)
        await self._refresh_token()

    async def close(self) -> None:
        """Close the aiohttp session. Call on bot shutdown."""
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        """Authenticate against Cognito and cache the IdToken."""
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
            self._token = resp["AuthenticationResult"]["IdToken"]
            # IdToken expires in 1 hour; refresh 5 minutes early
            self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=55)
            logger.info("Bot Cognito token refreshed.")
        except ClientError as e:
            logger.error("Failed to authenticate bot with Cognito: %s", e)
            raise

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
