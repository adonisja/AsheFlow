"""guild_config.py — per-company Discord guild configuration cache.

The bot fetches guild config from the backend's /internal/guild-config/{company_id}
endpoint on first use and caches the result for 5 minutes.  Stale entries are
invalidated on next access — no background refresh needed.

Usage:
    cfg = await get_guild_config(company_id)
    if cfg is None or not cfg.is_configured:
        return  # Discord not set up for this company — skip silently

    guild = bot.get_guild(cfg.guild_id)
    ...

The _guild_to_company reverse map lets on_member_join look up which company
owns a given guild_id so it can fetch the right config.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from time import monotonic
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300  # 5 minutes

_API_BASE = os.environ.get("API_BASE_URL", "http://backend:8000/api/v1")
_INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "change-me-in-production")

_cache: dict[str, tuple[float, "GuildConfig | None"]] = {}  # company_id -> (fetched_at, cfg)
_guild_to_company: dict[int, str] = {}   # guild_id -> company_id


@dataclass(frozen=True)
class GuildConfig:
    company_id:          str
    guild_id:            int
    drivers_channel_id:  Optional[int]
    trainers_channel_id: Optional[int]
    general_channel_id:  Optional[int]
    invite_channel_id:   Optional[int]
    role_admin:          Optional[int]
    role_manager:        Optional[int]
    role_asheflow:       Optional[int]
    role_bot:            Optional[int]
    role_dispatch:       Optional[int]
    role_driver:         Optional[int]
    role_captain:        Optional[int]
    role_walker:         Optional[int]

    @property
    def is_configured(self) -> bool:
        return self.guild_id is not None

    def always_allowed_role_ids(self) -> list[int]:
        """Role IDs that always have read access to ALL truck channels."""
        return [r for r in [
            self.role_admin,
            self.role_manager,
            self.role_asheflow,
            self.role_bot,
            self.role_dispatch,
        ] if r is not None]

    def privileged_role_ids(self) -> list[int]:
        """Full list of role IDs used by /setup-channels baseline."""
        return self.always_allowed_role_ids()


async def get_guild_config(company_id: str) -> Optional[GuildConfig]:
    """Return the GuildConfig for a company, using the 5-minute cache.

    Returns None if the company has no Discord config or the fetch fails.
    A returned GuildConfig with is_configured=False means Discord is not
    set up for this company — callers should skip Discord operations silently.
    """
    now = monotonic()
    cached = _cache.get(company_id)
    if cached is not None:
        fetched_at, cfg = cached
        if now - fetched_at < _CACHE_TTL_SECONDS:
            return cfg

    cfg = await _fetch_guild_config(company_id)
    _cache[company_id] = (now, cfg)

    if cfg is not None and cfg.guild_id is not None:
        _guild_to_company[cfg.guild_id] = company_id

    return cfg


async def _fetch_guild_config(company_id: str) -> Optional[GuildConfig]:
    url = f"{_API_BASE}/internal/guild-config/{company_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"X-Internal-Secret": _INTERNAL_SECRET},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 404:
                    logger.warning("Company %s not found in backend.", company_id)
                    return None
                if resp.status != 200:
                    logger.error("guild-config fetch for %s returned %d", company_id, resp.status)
                    return None
                data = await resp.json()
    except Exception as e:
        logger.error("Failed to fetch guild config for %s: %s", company_id, e)
        return None

    guild_id = data.get("guild_id")
    if guild_id is None:
        return None  # Discord not configured for this company

    return GuildConfig(
        company_id          = company_id,
        guild_id            = int(guild_id),
        drivers_channel_id  = data.get("drivers_channel_id"),
        trainers_channel_id = data.get("trainers_channel_id"),
        general_channel_id  = data.get("general_channel_id"),
        invite_channel_id   = data.get("invite_channel_id"),
        role_admin          = data.get("role_admin"),
        role_manager        = data.get("role_manager"),
        role_asheflow       = data.get("role_asheflow"),
        role_bot            = data.get("role_bot"),
        role_dispatch       = data.get("role_dispatch"),
        role_driver         = data.get("role_driver"),
        role_captain        = data.get("role_captain"),
        role_walker         = data.get("role_walker"),
    )


def get_company_id_for_guild(guild_id: int) -> Optional[str]:
    """Reverse-lookup: given a Discord guild_id, return the company_id.

    Returns None if the guild isn't in the map (bot hasn't fetched that
    company's config yet, or no company maps to this guild).
    """
    return _guild_to_company.get(guild_id)


def invalidate(company_id: str) -> None:
    """Remove a company's cached config so the next access re-fetches."""
    _cache.pop(company_id, None)
