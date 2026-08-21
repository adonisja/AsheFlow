"""ADP OAuth 2.0 token manager."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from .exceptions import ADPAuthError, ADPNetworkError

logger = logging.getLogger(__name__)


class ADPOAuthClient:
    """Manages OAuth 2.0 token exchange and refresh for ADP Workforce Now.

    Implements Client Credentials Grant flow. Caches tokens in-memory with
    automatic refresh 5 minutes before expiration.
    """

    TOKEN_ENDPOINT = "https://accounts.adp.com/auth/oauth/v2/token"
    TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        cert_pem: Optional[str] = None,
        key_pem: Optional[str] = None,
    ):
        """Initialize OAuth client.

        Args:
            client_id: ADP OAuth Client ID
            client_secret: ADP OAuth Client Secret
            cert_pem: mTLS certificate PEM (optional, added later)
            key_pem: mTLS private key PEM (optional, added later)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.cert_pem = cert_pem
        self.key_pem = key_pem

        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_token(self) -> str:
        """Get valid OAuth bearer token, refreshing if necessary.

        Returns:
            Valid OAuth 2.0 bearer token

        Raises:
            ADPAuthError: If token exchange fails
            ADPNetworkError: If network request fails
        """
        if self._is_token_valid():
            return self._token

        await self._refresh_token()
        return self._token

    def _is_token_valid(self) -> bool:
        """Check if cached token is still valid."""
        if self._token is None or self._token_expires_at is None:
            return False

        now = datetime.now(timezone.utc)
        time_until_expiry = self._token_expires_at - now

        return time_until_expiry > self.TOKEN_REFRESH_MARGIN

    async def _refresh_token(self) -> None:
        """Exchange credentials for new OAuth token.

        Updates self._token and self._token_expires_at on success.

        Raises:
            ADPAuthError: If token endpoint returns non-200
            ADPNetworkError: If network request fails
        """
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            cert = None
            if self.cert_pem and self.key_pem:
                cert = (self.cert_pem, self.key_pem)

            async with httpx.AsyncClient(cert=cert, verify=True) as client:
                response = await client.post(
                    self.TOKEN_ENDPOINT,
                    data=payload,
                    timeout=30.0,
                )
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.error("ADP OAuth token request failed: %s", e)
            raise ADPNetworkError(f"Failed to reach ADP token endpoint: {e}")

        if response.status_code != 200:
            logger.error(
                "ADP OAuth token exchange failed with status %s: %s",
                response.status_code,
                response.text,
            )
            raise ADPAuthError(
                response.status_code,
                "ADP authentication failed. Verify client ID/secret are correct.",
            )

        data = response.json()

        self._token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)

        if not self._token:
            logger.error("ADP token response missing access_token: %s", data)
            raise ADPAuthError(200, "Token endpoint returned invalid response")

        self._token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in
        )

        logger.debug(
            "ADP OAuth token refreshed. Expires at %s",
            self._token_expires_at.isoformat(),
        )

    def reset(self) -> None:
        """Reset cached token (useful for testing or credential rotation)."""
        self._token = None
        self._token_expires_at = None
