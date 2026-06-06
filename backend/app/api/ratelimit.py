"""Central SlowAPI limiter for AsheFlow.

Uses Redis as the storage backend (same instance as Celery broker) so limits
are shared across all worker processes and remain consistent under load.

Falls back to in-memory storage if Redis is unavailable — acceptable for
development but logs a warning so it is never silently degraded in production.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=settings.redis_url,
        default_limits=[],
    )
except Exception as exc:  # pragma: no cover
    logger.warning("SlowAPI Redis backend unavailable (%s) — falling back to in-memory.", exc)
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
