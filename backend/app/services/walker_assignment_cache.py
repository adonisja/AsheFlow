"""Redis cache helpers for walker/trainee assignment lookups.

Key schema: walker_assignment:{company_id}:{employee_id}:{date}
TTL: 300 seconds (5 minutes) — short enough to self-heal after missed invalidations,
     long enough to absorb mobile context-switch load.

Write-through invalidation is called by four endpoints after db.commit():
  - POST /truck-transfers         (create_transfers)
  - POST /wave-distribution       (wave_distribution — manual commit path)
  - PATCH /routes/{id}/reassign   (reassign_route)
  - (arrival-confirm excluded — does not change assignment ownership)
"""
import json
from datetime import date
from uuid import UUID

import redis as redis_lib

from app.core.config import settings

_TTL = 300  # 5 minutes


def _key(company_id: UUID, employee_id: UUID, route_date: date) -> str:
    return f"walker_assignment:{company_id}:{employee_id}:{route_date}"


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def get_cached_assignment(company_id: UUID, employee_id: UUID, route_date: date) -> dict | None:
    """Return cached assignment dict or None on miss/error."""
    try:
        raw = _redis().get(_key(company_id, employee_id, route_date))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def set_cached_assignment(company_id: UUID, employee_id: UUID, route_date: date, payload: dict) -> None:
    """Write payload to cache with TTL. Silently swallows Redis errors."""
    try:
        _redis().setex(_key(company_id, employee_id, route_date), _TTL, json.dumps(payload))
    except Exception:
        pass


def bust_walker_assignment_cache(company_id: UUID, employee_id: UUID, route_date: date) -> None:
    """Delete the cache entry for one walker on one date. Silently swallows errors."""
    try:
        _redis().delete(_key(company_id, employee_id, route_date))
    except Exception:
        pass
