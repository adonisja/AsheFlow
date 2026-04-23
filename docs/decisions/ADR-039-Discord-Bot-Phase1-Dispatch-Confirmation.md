# ADR-039: Discord Bot — Phase 1: Dispatch Confirmation System

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The original dispatch spec described Discord as the primary operational surface: after the coordinator runs dispatch, employees receive a DM with their assignment and a confirmation window to accept or decline. No bot code existed prior to this session. All API blockers (auth, manual assignment, RBAC) were already resolved.

---

## Decisions

### Architecture: One bot, multiple Cogs

A single `discord.py` bot with a Cog-based structure. Each future feature area (schedule lookup, ETA posting, etc.) gets its own Cog file. All Cogs share a singleton `AsheFlowClient` API wrapper. This avoids duplicate bots in the server, duplicate token management, and duplicate infra.

### Publish flow: web app → backend → bot → Discord

The coordinator clicks **Publish to Discord** in the web app. The backend:
1. Seeds all assigned employees as `pending` in Redis (`dispatch:confirmations:{date}`)
2. Fires `POST /internal/publish` to the bot's internal webhook server (port 8001)

The bot then:
1. Posts a summary embed to `#drivers-chat` with all truck assignments
2. DMs each assigned employee with their truck, role, crew, and two buttons (Confirm / Decline)

### Confirmation state: Redis, not PostgreSQL

Confirmations are ephemeral operational state — they matter today, are irrelevant tomorrow, and don't need to be joined against other tables. A Redis hash per date (`dispatch:confirmations:{date}`) with a 48-hour TTL is the right storage layer. This avoids a new DB migration and keeps the confirmation read/write path fast.

### Bot authentication: Cognito service account

The bot authenticates against Cognito with a dedicated `dispatch`-role service account (`BOT_USERNAME` / `BOT_PASSWORD`). The bot holds the `dispatch` role so it can call `POST /dispatch/{date}/confirmations` (any authenticated user) and `GET /dispatch/{date}/confirmations` (dispatch/admin). No special bot-specific auth was needed — the existing Cognito + `RoleChecker` system handles it.

### Internal webhook security: shared secret header

The backend fires the bot webhook with `X-Internal-Secret`. The bot rejects requests without a matching secret. Both services read `INTERNAL_SECRET` from the environment. This prevents external callers from triggering publishes directly to the bot.

### Confirmation buttons: `discord.ui.View` with `timeout=None`

Persistent views (no timeout) so buttons survive bot restarts. After one response the buttons are disabled — employees cannot change their answer. A decline triggers an immediate alert to `#drivers-chat` so the coordinator can act.

### `discord_id` added to dispatch GET response

The bot needs Discord user IDs to send DMs. `GET /dispatch/{date}` now includes `discord_id` per crew member alongside `employee_id`, `name`, and `role`.

---

## Consequences

**Positive:**
- Employees receive DMs with their assignment immediately after publish.
- Coordinator sees live confirmation status (✓ confirmed / ✗ declined / ⏱ pending) per crew member on the dispatch grid without leaving the web app.
- Declines surface immediately in `#drivers-chat` so reassignment can happen before departure.
- The Cog structure means future Discord features (schedule lookup, ETA posting) have a clear, isolated place to live.

**Negative / Trade-offs:**
- Employees must have DMs open from server members, or the bot falls back to a channel warning listing who it couldn't reach.
- The bot is a new process in the Docker stack — one more thing to run, configure, and keep healthy.
- Confirmation state lives in Redis, not the DB — cannot be queried in SQL reports or joined against assignment records. Acceptable for Phase 1; a `DispatchConfirmation` DB table can be added later if reporting needs it.

---

## Files Created / Modified

| File | Type |
|---|---|
| `bot/main.py` | New — bot entry point + internal webhook server |
| `bot/cogs/dispatch.py` | New — dispatch Cog (publish, DMs, button views) |
| `bot/services/api_client.py` | New — async API client with Cognito auth |
| `bot/config.py` | New — pydantic-settings config |
| `bot/requirements.txt` | New |
| `bot/Dockerfile` | New |
| `bot/.env.example` | New |
| `backend/app/core/redis.py` | New — Redis client + confirmation helpers |
| `backend/app/core/config.py` | Modified — added `redis_url`, `internal_secret` |
| `backend/app/routers/dispatch.py` | Modified — `discord_id` in crew response; 3 new endpoints |
| `backend/requirements.txt` | Modified — added `redis[asyncio]` |
| `docker-compose.yml` | Modified — added `bot` service; wired `BOT_INTERNAL_URL` + `INTERNAL_SECRET` to backend |
| `frontend/src/pages/DispatchDashboard.tsx` | Modified — Publish button, confirmation state, badges |
