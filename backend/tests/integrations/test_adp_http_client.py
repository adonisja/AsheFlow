"""Tests for ADP HTTP client with rate limiting and error handling."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.integrations.adp.http_client import ADPHTTPClient
from app.integrations.adp.oauth import ADPOAuthClient
from app.integrations.adp.exceptions import (
    ADPAuthError,
    ADPValidationError,
    ADPPermissionError,
    ADPNotFoundError,
    ADPRateLimitError,
    ADPServerError,
    ADPNetworkError,
)


@pytest.fixture
def oauth_client():
    """OAuth client pre-seeded with a valid cached token.

    Both _token AND _token_expires_at must be set — _is_token_valid() checks the
    expiry, so seeding only _token makes get_token() attempt a real refresh
    against the live ADP endpoint.
    """
    client = ADPOAuthClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )
    client._token = "valid-token"
    client._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    return client


@pytest.fixture
def http_client(oauth_client):
    """Create HTTP client for testing."""
    return ADPHTTPClient(oauth_client, max_concurrent_requests=5)


@pytest.mark.asyncio
async def test_get_success(http_client, oauth_client):
    """Test successful GET request."""
    response_data = {"workers": [{"associateOID": "G123"}]}

    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"workers": []}'
        mock_response.json.return_value = response_data

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        result = await http_client.get("/hr/v2/workers")

        assert result == response_data
        mock_async_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_empty_content(http_client, oauth_client):
    """Test GET request returning 204 No Content."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b''

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        result = await http_client.get("/hr/v2/workers")

        assert result == {}


@pytest.mark.asyncio
async def test_get_400_bad_request(http_client, oauth_client):
    """Test that 400 raises ADPValidationError."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b'{"error": "invalid filter"}'
        mock_response.json.return_value = {"error": "invalid filter"}

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPValidationError) as exc_info:
            await http_client.get("/hr/v2/workers?$filter=invalid")

        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_401_unauthorized_refresh_and_retry(http_client, oauth_client):
    """Test that 401 triggers token refresh and retry."""
    oauth_client._token = "expired-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with patch.object(
            oauth_client, "reset"
        ) as mock_reset, patch.object(
            oauth_client, "get_token", new_callable=AsyncMock
        ) as mock_get_token:
            mock_get_token.return_value = "new-token"

            mock_response_success = MagicMock()
            mock_response_success.status_code = 200
            mock_response_success.content = b'{"workers": []}'
            mock_response_success.json.return_value = {"workers": []}

            mock_async_client.get.side_effect = [
                mock_response,
                mock_response_success,
            ]

            result = await http_client.get("/hr/v2/workers")

            assert result == {"workers": []}
            mock_reset.assert_called_once()


@pytest.mark.asyncio
async def test_get_403_forbidden(http_client, oauth_client):
    """Test that 403 raises ADPPermissionError."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPPermissionError):
            await http_client.get("/hr/v2/workers")


@pytest.mark.asyncio
async def test_get_404_not_found(http_client, oauth_client):
    """Test that 404 raises ADPNotFoundError."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPNotFoundError):
            await http_client.get("/hr/v2/workers/G123")


@pytest.mark.asyncio
async def test_get_429_rate_limited_with_retry(http_client, oauth_client):
    """Test that 429 triggers backoff and retry."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "1"}

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.content = b'{"workers": []}'
        mock_response_success.json.return_value = {"workers": []}

        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = [
            mock_response_429,
            mock_response_success,
        ]
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await http_client.get("/hr/v2/workers")
            assert result == {"workers": []}


@pytest.mark.asyncio
async def test_get_429_rate_limited_max_retries_exceeded(
    http_client, oauth_client
):
    """Test that 429 raises ADPRateLimitError after max retries."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ADPRateLimitError):
                await http_client.get("/hr/v2/workers", max_retries=0)


@pytest.mark.asyncio
async def test_get_500_server_error_with_retry(http_client, oauth_client):
    """Test that 500 triggers exponential backoff and retry."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.content = b'{"error": "Internal server error"}'
        mock_response_500.json.return_value = {"error": "Internal server error"}

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.content = b'{"workers": []}'
        mock_response_success.json.return_value = {"workers": []}

        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = [
            mock_response_500,
            mock_response_success,
        ]
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await http_client.get("/hr/v2/workers")
            assert result == {"workers": []}


@pytest.mark.asyncio
async def test_get_500_max_retries_exceeded(http_client, oauth_client):
    """Test that 500 raises ADPServerError after max retries."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b'{"error": "Internal server error"}'
        mock_response.json.return_value = {"error": "Internal server error"}

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ADPServerError):
                await http_client.get("/hr/v2/workers", max_retries=0)


@pytest.mark.asyncio
async def test_get_network_error(http_client, oauth_client):
    """Test that network errors raise ADPNetworkError."""
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_async_client = AsyncMock()
        # Must be httpx.ConnectError — the client catches httpx.RequestError,
        # so a builtin ConnectionError would propagate uncaught.
        mock_async_client.get.side_effect = httpx.ConnectError("Failed to connect")
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        with pytest.raises(ADPNetworkError):
            await http_client.get("/hr/v2/workers")


@pytest.mark.asyncio
async def test_patch_success(http_client, oauth_client):
    """Test successful PATCH request."""
    response_data = {"entryID": "TC-123", "status": "Updated"}
    oauth_client._token = "valid-token"

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"entryID": "TC-123"}'
        mock_response.json.return_value = response_data

        mock_async_client = AsyncMock()
        mock_async_client.patch.return_value = mock_response
        mock_async_client.__aenter__.return_value = mock_async_client

        mock_client.return_value = mock_async_client

        result = await http_client.patch(
            "/time/v2/workers/G123/time-entries/TC-123",
            {"breaks": [{"breakOut": "12:00", "breakIn": "13:00"}]},
        )

        assert result == response_data


@pytest.mark.asyncio
async def test_concurrent_requests_never_exceed_semaphore_limit(oauth_client):
    """In-flight requests stay at or below max_concurrent_requests.

    ADP rate-limits on concurrency (~12 open sockets), so this bound is what
    keeps a bulk employee sync from tripping 429s.
    """
    client = ADPHTTPClient(
        oauth_client, max_concurrent_requests=3, requests_per_second=1000.0
    )

    in_flight = 0
    peak = 0

    async def _tracked_get(*args, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.01)
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"{}"
            resp.json.return_value = {}
            return resp
        finally:
            in_flight -= 1

    with patch("app.integrations.adp.http_client.httpx.AsyncClient") as mock_client:
        mock_async_client = AsyncMock()
        mock_async_client.get = _tracked_get
        mock_async_client.__aenter__.return_value = mock_async_client
        mock_client.return_value = mock_async_client

        await asyncio.gather(*(client.get(f"/path{i}") for i in range(12)))

    assert peak <= 3, f"semaphore breached: {peak} concurrent requests"
    assert peak > 1, "requests serialised entirely — semaphore not exercised"
