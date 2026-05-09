---
name: Discord multi-guild migration
description: Discord config moved from bot/.env to CompanyConfig DB — completed 2026-05-09
type: project
---

Discord guild/channel/role IDs have been migrated from `bot/.env` to `company_configs` table.

**Why:** Each company must have its own Discord server — a single bot token can serve multiple guilds, but guild/channel/role IDs are per-company.

**Status: COMPLETE** (2026-05-09)

**What was done:**
- Alembic migration `l3m4n5o6p7q8`: added 13 BigInteger columns to `company_configs`
- ORM `CompanyConfig` model updated with all Discord columns
- `DiscordGuildConfig` dataclass + `get_discord_config()` in `company_config.py`
- `GET /internal/guild-config/{company_id}` endpoint in `backend/app/routers/internal.py`
- `bot/services/guild_config.py`: `GuildConfig` dataclass, 5-min TTL cache, `_guild_to_company` reverse map
- `bot/config.py`: stripped all guild/channel/role fields; `extra = "ignore"` so stale `.env` keys are silently ignored
- All bot cogs (dispatch, invite, setup) updated to accept `company_id` and fetch config from service
- All backend webhook callers updated to include `company_id` in payload:
  - dispatch.py: publish + finalize
  - trucks.py: lockdown-channel
  - anchor_points.py: post-embed + post-to-channel (now uses `get_discord_config` for drivers channel)
  - tasks/dispatch_alerts.py: alert (now per-company)
  - api/deps.py: invite
- Frontend `DiscordConfigCard` added to super admin company detail page (`/superadmin/companies/:id`)

**REQUIRED ACTION — Backfill DSP Test Company (company1):**
Bot `.env` still has the original snowflake IDs. After running the migration, open super admin UI → DSP Test Company → Discord Integration → Configure, and paste the values from `bot/.env`:
- DISCORD_GUILD_ID → Guild ID
- DISCORD_GENERAL_CHANNEL_ID → General Channel
- DISCORD_DRIVERS_CHANNEL_ID → Drivers Channel
- DISCORD_TRAINERS_CHANNEL_ID → Trainers Channel
- DISCORD_INVITE_CHANNEL_ID → Invite Channel (if set)
- All DISCORD_ROLE_* fields → corresponding roles

**How to apply:** All Discord functionality is now graceful-no-op if a company has no Discord config. Multi-tenant is the default going forward.
