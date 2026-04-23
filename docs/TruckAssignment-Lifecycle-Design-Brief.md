# TruckAssignment Lifecycle — Design Brief
**Status:** Pending discussion — answers required before implementation  
**Last updated:** 2026-04-22

---

## What this document is

A structured brief for designing the full TruckAssignment lifecycle automation in AsheFlow. It captures the known real-world flow, maps it to what the system needs to do at each phase, and identifies the open questions that must be answered before code can be written.

This is not a spec. It becomes one once the questions are answered.

---

## What already exists in the codebase

| Component | State |
|---|---|
| `TruckAssignment.status` column | Exists in DB (`planned` / `active` / `completed`) but **never mutated** — always stays `planned` |
| Dispatch publish → Discord bot DM | Working — crew receives truck assignment + Confirm/Decline buttons |
| `DispatchConfirmation` table | Working — stores confirmed / declined / pending per employee per date |
| `Departure` model | Working — driver records `departed_at` and `returned_at` |
| `CheckIn` model | Working — field staff check in on field ops page |
| `VehicleInspection` model | Working — pre-trip inspection form exists |
| Confirmation window timer | Configurable via `CONFIRMATION_WINDOW_HOURS` in bot `.env` |
| Celery Beat | Now active — can run scheduled tasks (e.g. deadline enforcement) |
| Bot internal webhook | Working — backend can push events to the bot via `POST /internal/...` |

The core gap: **the `status` field is never updated**, so nothing downstream (fleet board, management dashboard, real-time crew status) can use it.

---

## The real-world morning timeline

### Phase 1 — Assignment & Confirmation (07:40 – 08:20)

| Time | Event | System action needed |
|---|---|---|
| 07:40 – 08:10 | Dispatcher publishes assignments | Bot DMs each crew member with assignment + Confirm/Decline buttons |
| 08:20 | **Driver hard deadline** | If driver has not confirmed → alert dispatcher immediately |
| 09:00 | **Crew soft deadline** | All remaining confirmations close |

**Confirmation statuses needed:**
- `pending` — no response yet
- `confirmed` — clicked Confirm
- `declined` — clicked Decline
- `no_show` — deadline passed, no response ← **does not exist yet**
- `late` — confirmed but physically distant from AP ← **open question (see §4 below)**

---

### Phase 2 — Truck Retrieval & Inspection (08:20 – 08:30)

| Time | Event | System action needed |
|---|---|---|
| 08:20+ | Driver signs into Amazon Flex app | Out of system scope (external app) |
| 08:20+ | Driver arrives at offsite lot | Out of system scope |
| 08:20 – 08:30 | Driver inspects truck (90s – 2min) | `VehicleInspection` record submitted via field ops |
| 08:30 | Driver receives dock number | Currently manual — open question whether system stores this |

**Gap:** If inspection fails (flat tire, truck won't start), the system has no "truck grounded" trigger. See §5 below.

---

### Phase 3 — Warehouse Staging & Loading (08:30 – 09:00)

| Time | Event | System action needed |
|---|---|---|
| 08:30 | Driver arrives at assigned dock | Out of system scope |
| 08:30 | Driver checks if area is staged | Open question — see §2 below |
| 08:30 – 09:00 | Packages loaded into truck | Out of system scope |

---

### Phase 4 — Finalization & Deployment (09:00 – 09:05)

| Time | Event | System action needed |
|---|---|---|
| 09:00 | All confirmations close | System posts official crew list to each truck's Discord channel |
| 09:05 | Drivers depart toward Anchor Point | `TruckAssignment.status` → `active`; `Departure.departed_at` recorded |
| 09:05 | Driver posts AP + ETA to truck channel | Open question — manual or bot-assisted? See §3 below |

---

### Phase 5 — Return & Closeout (end of day)

| Time | Event | System action needed |
|---|---|---|
| On return | Driver records return | `Departure.returned_at` recorded; `TruckAssignment.status` → `completed` |
| On return | Walker ratings submitted | Already gated by `rating_window_hours` from `departed_at` |

---

## The two status transitions that unlock everything downstream

These are confirmed requirements with no open questions — they can be implemented now:

```
planned → active    when Departure.departed_at is recorded for the driver on that date
active  → completed when Departure.returned_at is recorded for the driver on that date
```

This alone fixes:
- Fleet Today card (0/0 bug) — query `TruckAssignment.status = active`
- Management dashboard real-time fleet board
- Any future analytics segmented by shift state

---

## Open questions — answers required before full implementation

### 1. No-show driver protocol

**Scenario:** It is 08:21. The driver has not confirmed.

- Does the system auto-alert the dispatcher via Discord or web notification, or does it expect the dispatcher to notice manually?
- Is there a standby driver pool the system can pull from? If yes, how is it maintained — is it a separate role/flag on `Employee`, or a manually maintained list?
- If a standby driver is reassigned, does the original `TruckAssignment` get updated in place, or is a new one created?
- Who has authority to make the swap — dispatcher only, or management too?

---

### 2. Unstaged equipment — does the system need to know?

**Scenario:** Driver arrives at dock, area is not staged (missing paperwork, rabbit phones, chargers).

- Does AsheFlow need to record staged vs. unstaged? If yes, this is a new data point on the `Departure` or `TruckAssignment` record, or a new table.
- A "Report Unstaged" button in the bot (or field ops page) could let dispatch track which warehouse shifts are failing to prep lanes — is this worth tracking?
- Does an unstaged report need to generate a notification to anyone (warehouse supervisor, management)?

---

### 3. Anchor Point (AP) logic

**Scenario:** At 09:05, driver posts their AP and ETA to the truck's Discord channel.

- Is the Anchor Point pre-determined by the route (fixed per truck / per date), or does the driver choose it on the fly each morning?
- If pre-determined: should the system include a Google Maps link to the AP in the crew's initial DM at publish time?
- If manual: should the bot support a slash command like `/ap [Location] [ETA]` to format it cleanly for the crew channel, and store it on the `TruckAssignment` record?
- Does the system need to store the AP at all (for analytics / auditing), or is it purely operational communication?

---

### 4. Crew confirmation vs. physical presence

**Scenario:** A crew member confirms at 08:55 but is physically 20+ minutes from the Anchor Point.

- Should "confirmed" mean "I will be there" or "I am already nearby"?
- Is a `late` status needed distinct from `declined`? A declined slot needs immediate replacement; a late arrival may not.
- Is geo-checking (distance to AP) in scope? This would require the crew member's location, which has privacy implications.
- If a crew member is late to the AP, does the driver wait, or does the driver leave and the crew member travels separately?

---

### 5. Inspection failure / truck grounded

**Scenario:** At 08:25, driver submits a vehicle inspection with failures (flat tire, won't start).

- Should a failed inspection automatically alert the dispatcher?
- Is there a "DAF" (Damaged/Available-as-Found) or "truck grounded" status needed on `TruckAssignment`?
- If a truck is grounded, what is the recovery path? Swap driver to a backup vehicle? Cancel the truck's assignments for the day?
- Does the system need a backup vehicle pool separate from the main fleet?
- What is the latest a swap can be made before the 08:30 dock window is considered missed?

---

## Recommended implementation order

Once open questions are answered, the suggested build sequence is:

1. **Status transitions** (no open questions) — `planned → active → completed` on departure/return events. Unblocks fleet board immediately.
2. **No-show enforcement** — Celery Beat task at 08:20 and 09:00 to flag unconfirmed drivers and crew, generate dispatcher notifications.
3. **Official crew post** — At 09:05, bot posts finalized crew lists to each truck's Discord channel and master list to drivers' chat.
4. **Inspection failure alert** — On `VehicleInspection` with failures before 09:00, fire dispatcher notification.
5. **AP posting** — Depending on answer to Q3: either pre-populate in DM, or implement `/ap` slash command.
6. **Standby driver pool** — Depending on answer to Q1: new role/flag + reassignment endpoint + bot flow.
7. **Unstaged reporting** — Depending on answer to Q2: new field + bot button + notification routing.

---

## Notes from discussion.md (source of record)

The five blind spots and questions above were originally surfaced in `discussion.md` and are reproduced here for reference. The answers to all five need to be worked out with the operations team before the full lifecycle can be specced. The status transition (item 1 above) is the only piece that can proceed independently.
