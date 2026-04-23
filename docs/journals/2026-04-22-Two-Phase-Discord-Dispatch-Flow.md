# Journal: Two-Phase Discord Dispatch Flow

**Date:** 2026-04-22  
**Session context:** ADR-048 — Discord dispatch channel management redesign

---

## What was done

### Database
- Added `discord_channel_id (BigInteger, nullable)` to `trucks` table via migration `c3d4e5f6a1b2`
- Seeded all 7 truck channel IDs in the migration itself (Atlas → Omega)
- Added `discord_channel_id: Optional[int]` to `TruckResponse` schema

### Bot config
- Added to `bot/config.py`: `discord_trainers_channel_id`, all 8 Discord server role IDs (Admin, Manager, AsheFlow, Bot, Dispatch, Driver, Captain, Walker) with hardcoded defaults matching the AsheFlow Test Server
- Added `DISCORD_TRAINERS_CHANNEL_ID` to `bot/.env`

### Bot cog rewrite (`bot/cogs/dispatch.py`)
Complete rewrite of the dispatch cog to implement two-phase flow:

**Phase 1 (publish_assignments):**
- Drivers: DM with truck name, Confirm/Decline, 08:20 deadline
- All other roles: attendance-only DM, no truck details, 09:00 deadline
- Trainer DM still includes trainee pairing + phase (no truck name)
- Trainee DM still includes trainer pairing (no truck name)
- Errors reported to #drivers-chat

**Phase 2 (finalize_assignments):**
- Fetches confirmed crew from API
- Clears member-level overwrites on each truck channel
- Sets @everyone deny + privileged roles allow + confirmed crew allow
- Posts crew embed to truck channel (purges own prior messages first)
- DMs confirmed crew with final truck + crew details
- Posts master driver list to #drivers-chat
- All errors aggregated and reported to #drivers-chat

### Setup cog (`bot/cogs/setup.py`)
New `/setup-channels` slash command (admin only):
- Locks #drivers-chat to Driver role + privileged roles
- Locks #trainers-chat to Captain role + privileged roles
- Locks all truck channels to privileged roles only (baseline — crew granted per-day at finalization)
- Reports applied/errors back to caller

### Backend
- `POST /dispatch/{date}/finalize` endpoint — forwards to bot's `/internal/finalize`
- `app/tasks/dispatch_alerts.py` — Celery task at 09:05 AM: notifies dispatch/admin in-app + posts to #drivers-chat via `/internal/alert`
- `celery_app.py` — registered dispatch_alerts, added `dispatch-finalization-reminder` beat entry at 14:05 UTC

### Bot main.py
- `trigger_finalize()` method on bot
- `/internal/finalize` webhook handler
- `/internal/alert` webhook handler (for Celery reminder)
- All 3 registered in `start_webhook_server()`
- Added `cogs.setup` to COGS list
- Added `tree.sync()` call in `on_ready` to register slash commands

---

## Key decisions

- **Truck name withheld from non-drivers in Phase 1**: prevents information leak before assignments are final
- **Finalization is always manual**: Celery fires a reminder at 09:05 but dispatch pulls the trigger — ensures backfills are resolved before crew lists go public
- **Channel IDs in DB, not config**: allows adding trucks without bot restart; returned in TruckResponse schema
- **Per-day permission reset**: finalization clears member-level overwrites before re-applying — previous day's crew can't see today's channel

---

## Celery timezone
Set to `America/New_York` so beat schedule times are written as local Eastern time. DST is handled automatically — no manual UTC math needed. Beat times are: 03:00 (invite cleanup), 00:01 (training deadlines), 09:05 (dispatch finalization reminder).
