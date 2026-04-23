# ADR-047: Bot DM Trainer-Trainee Pairing + reset_on_graduation Flag

**Status:** Accepted  
**Date:** 2026-04-22  
**Author:** adonisja

---

## Context

Two gaps were identified after the Phase training system (ADR-046) landed:

1. **Bot DM pairing gap** — when dispatch DMs are sent at publish time, each employee sees their crew roster but there is no explicit callout of:
   - For a **trainee**: who their trainer is today
   - For a **trainer**: which trainee(s) they are responsible for, and what training phase each is on

   Without this, trainers had to mentally scan the roster embed to infer the pairing, and trainees had no direct notification of their trainer.

2. **Trainee graduation path for simulation accounts** — the `graduate_trainees` service unconditionally promotes any trainee with 5+ dispatches to walker. For accounts used in a simulation/demo cycle (e.g., Timmy Trainee, who is used for integration testing), promotion to walker is wrong — the correct behavior is to reset them back to Phase 1 trainee so the full training cycle can repeat.

---

## Decision

### 1. Bot DM pairing callout

Added role-specific pairing blocks appended to each DM's description:

- **Trainee DM:** Lists all trainers on their truck under `🎓 Your trainer today:`. Shows a warning if no trainer is assigned.
- **Trainer DM:** Lists each trainee on their truck under `📋 Your trainee(s) today:` with their current training phase fetched live from `GET /training/trainee/{id}`.

Phase lookup is non-blocking — if the API call fails, the phase displays as `?` so the DM is never dropped.

The helper `_fetch_trainee_phases()` in `bot/cogs/dispatch.py` handles the async API calls. A new `get_trainee_current_phase(trainee_id)` method was added to `bot/services/api_client.py`.

### 2. reset_on_graduation flag

Added `reset_on_graduation: Boolean` (default `False`) to the `employees` table (migration `b2c3d4e5f6a1`).

When `True`, `graduate_trainees.py` instead of promoting to walker:
- Deletes all `TrainingTask` rows for the trainee's records
- Deletes all `TrainingRecord` rows for the trainee
- Leaves role as `trainee`, leaving them at Phase 1 on next dispatch injection
- Nullifies open `TrainerContinuationRequest` rows as before
- Fires a `trainee_reset` notification (not `trainee_graduated`)

Timmy Trainee (`d16be5f0-c021-70de-6a50-cc22a3880062`) has `reset_on_graduation=True`.

---

## Alternatives Considered

- **Phase callout in channel embed only:** Rejected — the channel embed is public and the pairing info is most useful in the private DM where the trainer can act on it immediately.
- **Separate "pairing notification" after confirmation:** Considered — avoids wasting API calls on employees who decline. Deferred because it adds bot-side state tracking across events. The current approach fires at publish time, accepting that a small fraction of trainees will decline after seeing the pairing. No correctness risk.
- **Soft-reset (keep records, reset phase counter only):** Rejected — the training injection reads the last open record's `current_day_number` to determine next phase. Soft-resetting would require a dedicated "phase reset" field. Deleting records is simpler and equally correct for simulation accounts.

---

## Consequences

- Trainers immediately know who their trainee is and what phase they're on when their DM arrives.
- Trainees have a clear, unambiguous callout of their trainer in their DM.
- Simulation accounts (reset_on_graduation=True) cycle through the full training system without polluting the walker roster.
- The API call for phase lookup adds ~1 extra HTTP round-trip per trainer-per-crew during DM dispatch. Acceptable for the batch size (1–3 trainers typically).
