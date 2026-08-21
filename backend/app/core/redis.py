"""Redis client singleton for confirmation state storage.

Confirmations are stored as Redis hashes keyed by date:
  Key:   dispatch:confirmations:{YYYY-MM-DD}
  Field: {employee_id}
  Value: "pending" | "confirmed" | "declined" | "cancelled"

TTL is set to 48 hours so old records are cleaned up automatically.
"""

import redis.asyncio as aioredis
from app.core.config import settings

CONFIRMATION_TTL_SECONDS = 48 * 60 * 60  # 48 hours


def _make_key(dispatch_date: str) -> str:
    return f"dispatch:confirmations:{dispatch_date}"


# Lazy singleton — created on first use, reused thereafter.
_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def set_confirmation(dispatch_date: str, employee_id: str, status: str) -> None:
    """Write a single employee's confirmation status."""
    r = get_redis()
    key = _make_key(dispatch_date)
    await r.hset(key, str(employee_id), status)
    await r.expire(key, CONFIRMATION_TTL_SECONDS)


async def get_all_confirmations(dispatch_date: str) -> dict[str, str]:
    """Return all employee confirmation statuses for a date.

    Returns a dict of {employee_id: status}.
    Empty dict if no confirmations have been recorded yet.
    """
    r = get_redis()
    return await r.hgetall(_make_key(dispatch_date))


async def clear_confirmations(dispatch_date: str) -> None:
    """Delete all confirmation state for a date (called when dispatch is cleared)."""
    r = get_redis()
    await r.delete(_make_key(dispatch_date))


async def seed_pending(dispatch_date: str, employee_ids: list[str]) -> None:
    """Initialise every employee in the dispatch as 'pending'.

    Called when the coordinator clicks Publish. Only sets employees
    that don't already have an entry (idempotent re-publish).
    """
    r = get_redis()
    key = _make_key(dispatch_date)
    existing = await r.hgetall(key)
    for eid in employee_ids:
        if str(eid) not in existing:
            await r.hset(key, str(eid), "pending")
    await r.expire(key, CONFIRMATION_TTL_SECONDS)
