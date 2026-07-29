"""ADP HTTP client with rate limiting and error handling."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from .exceptions import (
    ADPAuthError,
    ADPNetworkError,
    ADPNotFoundError,
    ADPPermissionError,
    ADPRateLimitError,
    ADPServerError,
    ADPValidationError,
)
from .oauth import ADPOAuthClient

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adp.com"


class ADPHTTPClient:
    """HTTP client for ADP Workforce Now API with rate limiting and retry logic.

    Handles:
    - OAuth token management and refresh
    - Rate limit backoff (respects Retry-After header)
    - Error classification and retry decisions
    - Structured logging for debugging
    """

    def __init__(
        self,
        oauth_client: ADPOAuthClient,
        max_concurrent_requests: int = 10,
        requests_per_second: float = 10.0,
        burst_percent: int = 150,
    ):
        """Initialize HTTP client.

        Args:
            oauth_client: ADPOAuthClient instance for token management
            max_concurrent_requests: Max concurrent requests allowed
            requests_per_second: Target rate limit (requests per second)
            burst_percent: Burst allowance as percent (e.g., 150 = 150% of rate)
        """
        self.oauth = oauth_client
        self.max_concurrent = max_concurrent_requests
        self.requests_per_second = requests_per_second
        self.burst_percent = burst_percent

        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._request_times: list[float] = []
        self._last_rate_limit_reset = time.time()

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """GET request to ADP API.

        Args:
            path: API path (e.g., '/hr/v2/workers')
            params: Query parameters
            retry_count: Current retry count (internal)
            max_retries: Max retries on 5xx/429 errors

        Returns:
            Parsed JSON response

        Raises:
            ADPAuthError: Authentication failed (401)
            ADPPermissionError: Insufficient permissions (403)
            ADPNotFoundError: Resource not found (404)
            ADPValidationError: Request validation failed (400)
            ADPRateLimitError: Rate limited (429)
            ADPServerError: Server error (5xx)
            ADPNetworkError: Network error
        """
        async with self._semaphore:
            await self._respect_rate_limit()

            token = await self.oauth.get_token()
            headers = {"Authorization": f"Bearer {token}"}

            url = f"{BASE_URL}{path}"

            try:
                async with httpx.AsyncClient(verify=True) as client:
                    response = await client.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=30.0,
                    )
            except (httpx.TimeoutException, httpx.RequestError) as e:
                logger.error("ADP GET request failed: %s %s", path, e)
                raise ADPNetworkError(f"GET {path}: {e}")

            return await self._handle_response(
                response, path, retry_count, max_retries, "GET"
            )

    async def patch(
        self,
        path: str,
        json_body: Dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """PATCH request to ADP API.

        Args:
            path: API path
            json_body: Request body as dict
            retry_count: Current retry count (internal)
            max_retries: Max retries on 5xx/429 errors

        Returns:
            Parsed JSON response

        Raises:
            (See get() method)
        """
        async with self._semaphore:
            await self._respect_rate_limit()

            token = await self.oauth.get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            url = f"{BASE_URL}{path}"

            try:
                async with httpx.AsyncClient(verify=True) as client:
                    response = await client.patch(
                        url,
                        json=json_body,
                        headers=headers,
                        timeout=30.0,
                    )
            except (httpx.TimeoutException, httpx.RequestError) as e:
                logger.error("ADP PATCH request failed: %s %s", path, e)
                raise ADPNetworkError(f"PATCH {path}: {e}")

            return await self._handle_response(
                response, path, retry_count, max_retries, "PATCH"
            )

    async def _handle_response(
        self,
        response: httpx.Response,
        path: str,
        retry_count: int,
        max_retries: int,
        method: str,
    ) -> Dict[str, Any]:
        """Classify response and handle errors with retry logic.

        Args:
            response: httpx Response object
            path: API path (for logging)
            retry_count: Current retry attempt
            max_retries: Max retries allowed
            method: HTTP method (GET/PATCH/etc.)

        Returns:
            Parsed JSON response (on success)

        Raises:
            Various ADP exceptions based on status code
        """
        status = response.status_code

        if status == 200:
            logger.debug("%s %s returned 200", method, path)
            return response.json() if response.content else {}

        if status == 204:
            logger.debug("%s %s returned 204 (No Content)", method, path)
            return {}

        if status == 400:
            body = response.json() if response.content else {}
            logger.warning("%s %s returned 400: %s", method, path, body)
            raise ADPValidationError(status, body)

        if status == 401:
            logger.warning("%s %s returned 401 (Unauthorized)", method, path)
            self.oauth.reset()
            if retry_count < 1:
                logger.debug("Retrying with refreshed token")
                return await (
                    self.get(path, retry_count=retry_count + 1, max_retries=max_retries)
                    if method == "GET"
                    else self.patch(path, {}, retry_count=retry_count + 1, max_retries=max_retries)
                )
            raise ADPAuthError(status, "Authentication failed after token refresh")

        if status == 403:
            logger.warning("%s %s returned 403 (Forbidden)", method, path)
            raise ADPPermissionError(
                f"Client not authorized for {method} {path}"
            )

        if status == 404:
            logger.warning("%s %s returned 404 (Not Found)", method, path)
            raise ADPNotFoundError(path)

        if status == 429:
            retry_after = self._get_retry_after(response)
            logger.warning(
                "%s %s rate limited. Retry after %d seconds",
                method,
                path,
                retry_after,
            )

            if retry_count < max_retries:
                logger.debug("Sleeping %d seconds before retry", retry_after)
                await asyncio.sleep(retry_after)
                return await (
                    self.get(path, retry_count=retry_count + 1, max_retries=max_retries)
                    if method == "GET"
                    else self.patch(path, {}, retry_count=retry_count + 1, max_retries=max_retries)
                )

            raise ADPRateLimitError(retry_after)

        if 500 <= status < 600:
            body = response.json() if response.content else {}
            logger.error("%s %s returned %d: %s", method, path, status, body)

            if retry_count < max_retries:
                wait_time = min(2 ** retry_count, 32)
                logger.debug("Server error. Retrying after %d seconds", wait_time)
                await asyncio.sleep(wait_time)
                return await (
                    self.get(path, retry_count=retry_count + 1, max_retries=max_retries)
                    if method == "GET"
                    else self.patch(path, {}, retry_count=retry_count + 1, max_retries=max_retries)
                )

            raise ADPServerError(status, body)

        logger.error(
            "%s %s returned unexpected status %d", method, path, status
        )
        raise ADPServerError(
            status,
            response.json() if response.content else {},
        )

    async def _respect_rate_limit(self) -> None:
        """Apply rate limiting before making a request.

        Implements token bucket algorithm:
        - Base rate: requests_per_second
        - Burst: burst_percent above base for 60 seconds
        """
        now = time.time()

        self._request_times = [t for t in self._request_times if now - t < 60]

        min_interval = 1.0 / self.requests_per_second
        if self._request_times:
            time_since_last = now - self._request_times[-1]
            if time_since_last < min_interval:
                wait_time = min_interval - time_since_last
                logger.debug("Rate limiting: waiting %.2f seconds", wait_time)
                await asyncio.sleep(wait_time)

        self._request_times.append(time.time())

    @staticmethod
    def _get_retry_after(response: httpx.Response) -> int:
        """Extract Retry-After header or return exponential backoff value.

        Args:
            response: httpx Response object (assumed to be 429)

        Returns:
            Seconds to wait before retrying
        """
        if "Retry-After" in response.headers:
            try:
                return int(response.headers["Retry-After"])
            except ValueError:
                pass

        return 60
