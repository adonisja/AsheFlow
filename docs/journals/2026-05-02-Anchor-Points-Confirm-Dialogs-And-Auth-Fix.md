# Journal — Anchor Points Rewrite, Confirm Dialogs, and Auth Fix
**Date:** 2026-05-02 (afternoon session)

## What we did

### Anchor point lifecycle rewrite

The original anchor point model was designed for end-of-day submissions — one row per truck per day. The actual business flow requires three distinct events: a preliminary AP before departure (with ETA), an arrival confirmation on reaching the spot, and optional mid-day relocations if the driver moves. None of this fit the single-row model.

We dropped the `UniqueConstraint("truck_id", "date")` and added `sequence`, `is_initial`, `status` (preliminary/arrived/relocated), and `arrived_at`. The router was rewritten around this lifecycle: `POST /` creates the AP and marks any previous active row as relocated, `PATCH /{id}/arrive` stamps arrival, and `GET /truck/{id}` returns only `is_initial=True` rows so next-day driver suggestions show planned departure locations rather than mid-day moves.

Two 403/404 bugs fell out of this: drivers couldn't read truck AP history because `allow_truck_read` excluded the driver role, and the dock-assignment endpoint was raising 404 for unassigned drivers (a normal state before dispatch runs), filling the console with noise. Both fixed.

AnchorPoints.tsx was fully rewritten — driver view has a status timeline, a preliminary form with history suggestions, and a one-tap arrived card. FieldOps.tsx AnchorPointPanel simplified to a compact card linking to the full page.

### Discord AP embeds

The AP notifications were plain text strings. Added `POST /internal/post-embed` to the bot (accepts title, color, fields array, footer — builds a `discord.Embed`). All three AP events now fire color-coded embeds to the truck channel: amber for preliminary, green for arrived, purple for relocated.

### Confirm dialogs across the app

A lot of buttons sent requests immediately with no confirmation gate. Built a shared `ConfirmDialog` component and `useConfirm` hook (Promise-based — callers `await confirm({...})` and early-return on false). Wired into Schedule, ScheduleChanges, DispatchView, Incidents, FeedbackAdmin, Assets (three sub-components, three hook instances), and Preferences.

### Admin identity and confirm-all fix

The "Confirm All Pending" dev tool on AdminDashboard was broken in two ways:

1. `res.data` was being iterated instead of `res.data.confirmations` — the GET response wraps the map under a `confirmations` key, so `pending` was always empty. Fixed the destructuring.

2. After that fix, it still 403'd — `get_caller_employee` couldn't find an `Employee` row for the logged-in account (`test@example.com`), so it raised 403 before the body ran.

First attempt was a `confirm-all` bulk endpoint that bypassed employee resolution entirely. That was a mistake — it had no audit attribution and accepted any dispatch-group Cognito token. Reverted it.

The right fix: insert one `Employee` row for the admin account so `get_caller_employee` resolves normally. The existing privileged-role bypass in `record_confirmation` (`caller.role in {"dispatch", "management", "admin"}`) already handles the rest.

Also made the confirm-all card conditional — it's hidden until there are actual pending confirmations, checked on page load with a silent GET.

## What I learned

**The confirm-all detour was a good lesson in where shortcuts hide.** The endpoint worked, but only by removing the constraint that made the original endpoint trustworthy. The identity gap (no employee row for the admin account) was a five-second DB insert; the bulk endpoint was a much larger change that traded away audit trail and authorization scope for convenience. When you're blocked on auth, fix the identity — don't route around the auth check.

**Multiple `useConfirm` instances per file.** React hooks can't be called conditionally, and each sub-component that renders its own return tree needs its own hook instance and its own `ConfirmDialog` in that return. Assets.tsx has three tabs (PeopleTab, FleetTab, SystemTab) — each needed its own. The pattern is mechanical: declare the hook at the top of the function, put `<ConfirmDialog {...confirmState} onCancel={cancelConfirm} />` in the return, replace `window.confirm(...)` with `await confirm({...})`. Getting any one of those three wrong produces TypeScript "declared but never read" hints that make it easy to spot.

**`is_initial` over a sequence filter.** Using a dedicated boolean column for "first AP of the day" is cleaner than `WHERE sequence = 1` because it survives edge cases: if the first AP were deleted (unlikely but possible), `sequence = 1` would misidentify the new first row. `is_initial` is stamped at insert time and never changes.

---

### Schedule change request approve 404

`PATCH /schedule-change-requests/{id}/approve` was returning 404 when clicking Approve on a rework request in the Schedule management view. The backend query filters `WHERE status = 'pending'` and returns 404 for anything else — intentional, since approving an already-resolved request would corrupt the schedule.

The frontend fetch at load time was `GET /schedule-change-requests/` with no filter, so approved and rejected rework requests appeared in the pending queue alongside genuinely pending ones. Clicking Approve on an already-approved item sent a valid UUID to an endpoint that correctly couldn't find a pending row for it.

**Fix:** `GET /schedule-change-requests/?status=pending` — one query param, one line changed ([Schedule.tsx:114](../frontend/src/pages/Schedule.tsx)). The `allReworks` fetch used for analytics counters stays unfiltered intentionally.

---

### Redis confirmation cache lost on container restart → finalization shows TBD drivers

**Symptom:** After running Finalize Dispatch, the #drivers-chat post showed `Driver: TBD` for most trucks even though all drivers were confirmed on the dispatch board.

**Root cause:** Confirmation state is stored in two places — the DB (`dispatch_confirmations` table, authoritative) and Redis (read cache, keyed `dispatch:confirmations:{date}`). When `docker compose up -d` restarted the backend and bot containers earlier in the session, Redis was also restarted, flushing its in-memory state. The `GET /dispatch/{date}/confirmations` endpoint read exclusively from Redis via `get_all_confirmations()` with no DB fallback. Redis returned an empty dict, so `finalize_assignments` in the bot saw every employee as `pending`, filtered `confirmed_crew` to empty, and had no driver to display per truck.

**Confirmed via:**
```
docker exec asheflow_redis redis-cli HGETALL "dispatch:confirmations:2026-05-02"
# → (empty)

SELECT name, role, status FROM dispatch_confirmations JOIN employees ...
# → all 5 drivers: confirmed
```

**Fix:** `GET /{dispatch_date}/confirmations` in [dispatch.py](../backend/app/routers/dispatch.py) now falls back to DB when Redis returns empty, then re-seeds Redis from the DB result so all subsequent reads are fast. Redis is now a true read-cache — a cold start is transparent to callers.

```python
if not confirmations:
    rows = db.query(DispatchConfirmation).filter(...).all()
    confirmations = {str(r.employee_id): r.status for r in rows}
    # re-seed Redis
    for eid, status_val in confirmations.items():
        await set_confirmation(str(dispatch_date), eid, status_val)
```

**Why this wasn't caught earlier:** The bug only surfaces after a Redis restart between Publish and Finalize. During normal operation Redis is warm the whole day. Container restarts during development are common and silently flush state.

**Secondary fixes in the same session:**
- Discord finalization post formatting: emoji inside code blocks break monospace alignment (Discord renders emoji as double-width). Moved all emoji outside the `` ``` `` block; inner content is pure ASCII. Purge of previous messages removed — channel history is the compliance log.
- `discord_id` values in the DB are username strings (`name#0000`), not snowflake integers. All `int(discord_id)` call sites now guard with `.isdigit()` and log a warning instead of raising `ValueError` into the error banner.

---

### Discord crew card — terminal-chic design (ADR-058)

Multiple iterations were required to land the final crew card format. Key findings:

- **The bot does not hot-reload** — every code change requires `docker compose restart bot` at minimum. Running stale code in memory was the root cause of several "edit had no effect" iterations this session. Backend uses uvicorn `--reload`; bot is plain `python main.py`.
- **25-field Discord limit** — any layout that uses one field per name hits this with large crews. The fix is one field per section, not one field per name.
- **Space-padding in backticks produces fixed-width pills** — `f"\`{name:<16}\`"` right-pads with spaces so both columns are always equal width in Discord's monospace font.
- **Emoji in code blocks break alignment** — Discord renders emoji as double-width in monospace. All emoji stay outside backtick/code-block content.
- **Driver and Trainers share one embed field** — separate fields produce unwanted whitespace between them. Combining with `\n\n` gives the correct tight spacing.

Final structure: truck name as wide centered pill (no divider above, single divider below) → Crew Leadership field (driver pill + blank line + trainers pills) → divider + Walkers → divider + Trainees → divider in footer + dispatch date. See ADR-058 for full implementation guide.

---

### AP arrival → #drivers-chat update

When a driver confirms AP arrival the embed fires only to their truck channel. Dispatch monitors #drivers-chat and shouldn't need to open each truck channel to see where trucks are parked.

**Fix:** `PATCH /{anchor_id}/arrive` now also calls `/internal/post-to-channel` with `DISCORD_DRIVERS_CHANNEL_ID` after posting the truck-channel embed. Message format: `📍 **{truck_name}** — {driver} confirmed AP: **{location}**`.

`DISCORD_DRIVERS_CHANNEL_ID` is sourced from `backend/.env` and mounted into the backend container via `env_file` in `docker-compose.yml`. The backend already reads `BOT_INTERNAL_URL` / `INTERNAL_SECRET` the same way; this follows the same pattern.

Guard: the channel post is skipped if `DISCORD_DRIVERS_CHANNEL_ID` is unset or non-numeric, so dev environments without a Discord config are unaffected.
