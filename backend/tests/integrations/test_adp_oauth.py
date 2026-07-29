"""Tests for ADP OAuth token manager."""

import httpx
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.integrations.adp.oauth import ADPOAuthClient
from app.integrations.adp.exceptions import ADPAuthError, ADPNetworkError


@pytest.fixture
def oauth_client():
    """Create OAuth client for testing."""
    return ADPOAuthClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


@pytest.fixture
def valid_token_response():
    """Mock successful token response from ADP."""
    return {
        "access_token": "eyJhbGc...",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "hr:worker:read time:timecard:read payroll:pay-period:read",
    }


@pytest.mark.asyncio
async def test_get_token_first_time(oauth_client, valid_token_response):
    """Test getting token for the first time."""
    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = valid_token_response

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        token = await oauth_client.get_token()

        assert token == "eyJhbGc..."
        assert oauth_client._token is not None
        assert oauth_client._token_expires_at is not None
        mock_async_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_get_token_cached(oauth_client, valid_token_response):
    """Test that cached token is reused if still valid."""
    oauth_client._token = "cached-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    token = await oauth_client.get_token()

    assert token == "cached-token"


@pytest.mark.asyncio
async def test_get_token_refresh_on_expiry(oauth_client, valid_token_response):
    """Test that token is refreshed when nearly expired."""
    oauth_client._token = "old-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=3
    )

    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = valid_token_response

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        token = await oauth_client.get_token()

        assert token == "eyJhbGc..."
        assert oauth_client._token != "old-token"


@pytest.mark.asyncio
async def test_auth_error_on_invalid_credentials(oauth_client):
    """Test that ADPAuthError is raised on 401 response."""
    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid client credentials"

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPAuthError) as exc_info:
            await oauth_client.get_token()

        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_error_missing_token_in_response(oauth_client):
    """Test that ADPAuthError is raised if response missing access_token."""
    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token_type": "Bearer"}

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPAuthError) as exc_info:
            await oauth_client.get_token()

        assert "invalid response" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_network_error_on_timeout(oauth_client):
    """Test that ADPNetworkError is raised on network timeout.

    The client catches httpx.TimeoutException specifically — a builtin
    TimeoutError would propagate uncaught, so the mock must raise httpx's type.
    """
    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_async_client = AsyncMock()
        mock_async_client.post.side_effect = httpx.TimeoutException("Connection timeout")
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPNetworkError):
            await oauth_client.get_token()


@pytest.mark.asyncio
async def test_network_error_on_connection_error(oauth_client):
    """Test that ADPNetworkError is raised on connection error."""
    with patch("app.integrations.adp.oauth.httpx.AsyncClient") as mock_client:
        mock_async_client = AsyncMock()
        mock_async_client.post.side_effect = httpx.ConnectError("Failed to connect")
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPNetworkError):
            await oauth_client.get_token()


def test_is_token_valid_no_token(oauth_client):
    """Test that no cached token is considered invalid."""
    assert oauth_client._is_token_valid() is False


def test_is_token_valid_expired_token(oauth_client):
    """Test that expired token is considered invalid."""
    oauth_client._token = "expired-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) - timedelta(
        hours=1
    )

    assert oauth_client._is_token_valid() is False


def test_is_token_valid_expiring_soon(oauth_client):
    """Test that token expiring within margin is considered invalid."""
    oauth_client._token = "expiring-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=2
    )

    assert oauth_client._is_token_valid() is False


def test_is_token_valid_valid_token(oauth_client):
    """Test that token valid beyond margin is considered valid."""
    oauth_client._token = "valid-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    assert oauth_client._is_token_valid() is True


def test_reset(oauth_client):
    """Test that reset clears cached token."""
    oauth_client._token = "some-token"
    oauth_client._token_expires_at = datetime.now(timezone.utc) + timedelta(
        hours=1
    )

    oauth_client.reset()

    assert oauth_client._token is None
    assert oauth_client._token_expires_at is None
