# Journal: Discord Bot — Phase 1 (Dispatch Confirmation)
**Date:** 2026-04-16

---

## Context

Built the Discord bot from scratch. All API blockers were already resolved. Phase 1 scope: one-way publish (web app → Discord), per-employee DMs with Confirm/Decline buttons, and live confirmation status badges in the dispatch grid.

---

## What Was Built

### Bot (`bot/`)

| File | Purpose |
|---|---|
| `main.py` | Bot entry point. Loads cogs, starts `AsheFlowClient`, runs an internal `aiohttp` webhook server on port 8001 that receives publish triggers from the backend. |
| `config.py` | `pydantic-settings` config reading from `.env`. Fields: bot token, channel/guild IDs, API URL, Cognito credentials, confirmation window hours. |
| `cogs/dispatch.py` | `DispatchCog` — `publish_assignments()` posts truck embeds to `#drivers-chat` then DMs each employee with a `ConfirmationView`. Buttons call `POST /dispatch/{date}/confirmations`. Declined employees trigger a channel alert. |
| `services/api_client.py` | `AsheFlowClient` — async `aiohttp` wrapper with Cognito `USER_PASSWORD_AUTH` token management (55-minute refresh cycle). Methods: `get_dispatch`, `get_trucks`, `post_confirmation`, `get_confirmations`, `publish_dispatch`. |
| `requirements.txt` | `discord.py==2.3.2`, `aiohttp==3.9.3`, `boto3`, `pydantic-settings` |
| `Dockerfile` | `python:3.11-slim`, installs requirements, runs `main.py` |
| `.env.example` | All required env vars documented with explanations |

### Backend changes

**`backend/app/core/redis.py`** — New module. Redis hash per date: `dispatch:confirmations:{YYYY-MM-DD}`. Functions: `set_confirmation`, `get_all_confirmations`, `seed_pending` (idempotent init of all employees to `pending`). 48-hour TTL.

**`backend/app/core/config.py`** — Added `redis_url` (default: `redis://localhost:6379/0`) and `internal_secret`.

**`backend/app/routers/dispatch.py`** — Three new endpoints:
- `POST /{date}/publish` — seeds Redis, fires bot webhook via `aiohttp`
- `POST /{date}/confirmations` — records one employee's response (any authenticated user — bot service account)
- `GET /{date}/confirmations` — returns full confirmation map (dispatch/admin)

Also: `discord_id` added to each crew member dict in `GET /{date}`.

**`backend/requirements.txt`** — Added `redis[asyncio]==5.0.1`.

### Docker Compose

Added `bot` service: builds from `./bot`, reads `./bot/.env`, exposes port 8001, depends on `backend` + `redis`. Wired `BOT_INTERNAL_URL=http://bot:8001` and `INTERNAL_SECRET` into the backend service environment.

### Frontend (`frontend/src/pages/DispatchDashboard.tsx`)

- New imports: `Send`, `CheckCircle2`, `XCircle`, `Clock` from lucide-react
- New state: `isPublishing` (button loading), `confirmations` (Record<employeeId, status>)
- `fetchConfirmations()` — calls `GET /dispatch/{date}/confirmations`, called on date change and refresh
- `handlePublishToDiscord()` — calls `POST /dispatch/{date}/publish` with confirm dialog
- **Publish to Discord** button (green, `Send` icon) — disabled until dispatch exists
- Confirmation badges per crew member card: ✓ green (`confirmed`), ✗ red (`declined`), ⏱ yellow (`pending`)

---

## Key Design Choices

- **Redis over DB for confirmation state** — ephemeral, no joins needed, 48h TTL handles cleanup automatically
- **`timeout=None` on button views** — buttons survive bot restarts
- **Shared secret on internal webhook** — prevents external publish triggers
- **DM failures surface in channel** — coordinator knows immediately who to contact manually

---

## What's Next (Phase 2)

- `/schedule` slash command — employee queries their assignment for a date
- `/eta` command — driver posts ETA back to channel
- Auto-close confirmation window after `CONFIRMATION_WINDOW_HOURS`
