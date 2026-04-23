# ADR-048: Two-Phase Discord Dispatch Flow

**Status:** Accepted  
**Date:** 2026-04-22  
**Author:** adonisja

---

## Context

The existing dispatch publish flow sent a single DM to every crew member with their truck name, full crew list, and a Confirm/Decline button. Several problems with this:

1. **Information leak** — walkers, trainees, and trainers received their truck name before assignments were confirmed. If a driver declines, their truck assignment changes, but crew members already know the wrong truck.

2. **No finalization step** — after confirmations, there was no mechanism to post the official crew list to the truck's Discord channel or manage who can see that channel for the day.

3. **No channel access control** — truck channels were publicly accessible (or accessible to all members) with no per-day restriction to the assigned crew.

4. **No deadline pressure to dispatch** — nothing in the system reminded dispatch that the 09:10 AM finalization window was approaching.

---

## Decision

### Two-phase flow

**Phase 1 — Publish (07:40–08:10 AM, triggered manually by dispatch):**
- Drivers DM: truck name + Confirm/Decline, deadline 08:20 AM
- All other roles DM: attendance-only request ("you have an assignment today"), no truck details, deadline 09:00 AM
- Trainers still receive trainee pairing + phase in their DM (doesn't reveal truck)
- Trainees still receive trainer pairing in their DM
- Declines immediately post to `#drivers-chat` so dispatch can backfill

**Phase 2 — Finalize (~09:10 AM, triggered manually by dispatch):**
- Bot fetches confirmed crew from the API
- Clears existing per-member permission overwrites on each truck channel
- Denies `@everyone`, grants permanently privileged roles (Admin, Manager, AsheFlow, Bot, Dispatch)
- Grants confirmed crew members individual channel access
- Posts crew embed to truck channel
- DMs each confirmed crew member with their final truck name + full confirmed crew list
- Posts master driver/truck list to `#drivers-chat`
- All errors reported to `#drivers-chat` so dispatch sees them

### 09:05 AM Celery alert

At 09:05 AM (14:05 UTC / 13:05 UTC during EDT), Celery fires:
- In-app Notification to all active dispatch/admin employees
- Bot posts alert to `#drivers-chat`: "Finalization deadline approaching — please finalize by 09:10"

The actual finalization is always manual — dispatch clicks "Finalize" in the web app.

### Permanent channel baseline (`/setup-channels`)

A one-time admin slash command sets the server's baseline permissions:
- `#drivers-chat`: @everyone denied, Driver role allowed, privileged roles allowed
- `#trainers-chat`: @everyone denied, Captain (Trainer) role allowed, privileged roles allowed
- All truck channels: @everyone denied, privileged roles allowed, no crew access by default

Crew access on truck channels is reset and re-granted per-day at finalization time. The baseline ensures channels are locked even on days with no dispatch.

### Truck → Discord channel mapping

`discord_channel_id (BigInteger)` added to the `trucks` table (migration `c3d4e5f6a1b2`). Channel IDs are seeded at migration time and returned in `GET /trucks/` via `TruckResponse`. The bot reads this field at finalization — no hardcoded channel map in code.

---

## Alternatives Considered

- **Send truck name to all roles in Phase 1:** Rejected — information leak if driver declines and gets swapped. Crew shouldn't know their truck until assignments are final.
- **Auto-finalize at 09:10 via Celery:** Rejected — dispatch needs to confirm all manual backfills are done before posting. A missed backfill would post an incomplete crew list to the channel. Manual trigger with automated reminder is the right balance.
- **Hardcode truck→channel map in bot config:** Rejected — channel IDs are operational data that live alongside truck records in the DB. Putting them in config would require a bot restart to add a new truck.

---

## Consequences

- Crew members only learn their truck at finalization, after all confirmations are resolved.
- Truck channels are locked by default and opened per-day to the confirmed crew only.
- Dispatch/management/admin always have read access to all truck channels regardless of assignment.
- The 09:05 AM reminder reduces the likelihood of dispatch missing the finalization window.
- The `/setup-channels` command is idempotent and safe to re-run after adding new truck channels.

---

## Files Changed

- `backend/alembic/versions/c3d4e5f6a1b2_add_discord_channel_id_to_trucks.py` (new)
- `backend/app/models/truck.py`
- `backend/app/schemas/truck.py`
- `backend/app/routers/dispatch.py` — added `POST /{date}/finalize`
- `backend/app/tasks/dispatch_alerts.py` (new)
- `backend/app/celery_app.py` — added dispatch_alerts task + beat schedule
- `bot/config.py` — added role IDs, trainers-chat ID
- `bot/.env` — added DISCORD_TRAINERS_CHANNEL_ID
- `bot/cogs/dispatch.py` — full rewrite: split DMs, finalize flow, channel permissions
- `bot/cogs/setup.py` (new) — `/setup-channels` slash command
- `bot/main.py` — added trigger_finalize, /internal/finalize, /internal/alert webhooks, slash command sync
- `bot/services/api_client.py` — updated get_confirmations return type
