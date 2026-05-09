# ADR-082 — Discord Multi-Guild: Per-Company Guild Config in DB

**Date:** 2026-05-09  
**Status:** Accepted  
**Context:** Discord bot multi-tenancy — each DSP company has its own Discord server

---

## Context

The Discord bot was originally hardcoded for a single guild. All guild ID, channel IDs, and role IDs lived in `bot/.env`. This meant:

1. Only one company could use Discord features at a time.
2. Adding a second tenant would require redeploying the bot with different env vars or running separate bot instances.
3. Config was split between `bot/.env` and the DB, which made the system harder to reason about.

The goal was to move all per-company Discord IDs into the `company_configs` table so a single bot token can serve multiple guilds, with each company's config fetched at runtime.

---

## Decision

### DB schema

Alembic migration `l3m4n5o6p7q8` adds 13 `BigInteger` nullable columns to `company_configs`:

- `discord_guild_id`, `discord_general_channel_id`, `discord_drivers_channel_id`, `discord_trainers_channel_id`, `discord_invite_channel_id`
- `discord_role_admin`, `discord_role_manager`, `discord_role_asheflow`, `discord_role_bot`, `discord_role_dispatch`, `discord_role_driver`, `discord_role_captain`, `discord_role_walker`

All nullable — companies without Discord just don't set them, and all bot operations are graceful no-ops.

### Backend internal endpoint

`GET /internal/guild-config/{company_id}` (in `routers/internal.py`) — bot-facing, authenticated by `X-Internal-Secret` header. Returns all 13 fields. Returns 200 with all-null fields if Discord is unconfigured (not 404), so the bot never crashes on an unconfigured company.

`/internal/*` routes are exempt from Cognito auth and the `require_configured` middleware.

### Bot-side config service

`bot/services/guild_config.py`:
- `GuildConfig` frozen dataclass with `is_configured`, `always_allowed_role_ids()`, and `privileged_role_ids()` convenience methods
- 5-minute TTL in-memory cache keyed by `company_id`
- `_guild_to_company: dict[int, str]` reverse map populated on first fetch — used by `on_member_join` to identify which company a guild belongs to without hardcoding

`bot/config.py` had all guild/channel/role fields removed. Added `extra = "ignore"` to Pydantic's inner `Config` class so stale `.env` keys (still present in the file) are silently dropped rather than crashing startup with `Extra inputs are not permitted`.

### Graceful no-op pattern

Every bot operation (publish, finalize, lockdown-channel, invite, member-join) calls `get_guild_config(company_id)` and checks `cfg.is_configured`. If not configured, the function logs and returns without raising. This allows onboarding new companies incrementally without breaking the bot for existing ones.

### `company_id` propagated in all webhook payloads

All backend webhook callers updated to include `"company_id": str(caller.company_id)`:
- `dispatch.py` — publish and finalize
- `trucks.py` — lockdown-channel
- `anchor_points.py` — post-embed and post-to-channel (also replaced `os.environ.get("DISCORD_DRIVERS_CHANNEL_ID")` env var with `get_discord_config(db, caller.company_id)`)
- `tasks/dispatch_alerts.py` — now loops per company instead of issuing a single alert
- `api/deps.py` — invite

### Super admin UI

`DiscordConfigCard` added to the company detail page (`/superadmin/companies/:id`). Shows connected/not-configured badge, a read view with all 13 fields, and an edit form with snowflake inputs. Saves via `PATCH /admin/companies/{id}/discord-config`.

### Super admin layout navigation freeze (discovered during this work)

`SuperAdminLayout.tsx` had `AnimatePresence mode="wait"` wrapping `<Outlet />`. This mode holds the incoming page render until the outgoing page's exit animation (350ms) fully completes, which — combined with the `loading=true` skeleton state — made navigation appear frozen. Removed `AnimatePresence` and `motion.div` entirely, leaving a plain `<Outlet />`. During cleanup, `useLocation` was removed from the import line but its call site in the component body was left behind, causing a runtime crash. Both were removed in a follow-up edit.

---

## Alternatives considered

**Separate bot instance per company:** Simplest isolation but operationally expensive — N bot processes for N companies. Rejected in favor of one bot serving all guilds.

**Guild ID in every webhook payload vs. company_id:** Sending raw guild IDs avoids the backend lookup but requires the bot to know the guild–company mapping from a second source. Sending `company_id` keeps the bot's single source of truth in the backend.

**Env-var-per-company block in `.env`:** Using prefixed vars like `COMPANY1_DISCORD_GUILD_ID` would work for a small fixed tenant count but doesn't scale and requires a bot restart to add a tenant. Rejected.

---

## Consequences

- One bot token, one process, any number of Discord servers
- New tenants get Discord integration by filling in their config in the super admin UI — no deployments
- All Discord operations are graceful no-ops for companies without config
- Existing company1 Discord IDs must be backfilled via super admin UI (values are in `bot/.env`)
- `bot/.env` still holds the original snowflake values but they are no longer read at startup
