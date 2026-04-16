# ADR-019: Fix Dispatch Ban Conflict Warning False Positives

**Date:** 2026-04-14
**Status:** Accepted
**Area:** Dispatch / assign_walkers

---

## Context

During a live dispatch run, a ban conflict warning was surfaced in the dispatch UI showing that Damien Hurst (walker) had a ban conflict with Carlos Mendez (trainer). Upon inspection, the two employees were not on the same truck — Damien had been placed on a truck that Carlos was not on.

The warning was factually incorrect. It described a conflict that did not exist in the final assignment.

---

## Root Cause

In `assign_walkers.py`, the round-robin even-distribution constraint requires that walkers be placed on minimum-count trucks first. When a walker's hard-ban list (`hard_banned`) includes all trucks currently at the minimum count, the algorithm falls back to placing the walker on any unbanned truck.

The warning emission was located at the *entry point* of this fallback path — before `selected_truck` was determined:

```python
else:
    # fallback path entered
    banned_by = [banner_id for _, banner_id, _ in raw_bans]
    warnings.append({"employee_id": walker.id, "banned_by": banned_by})  # ← emitted here

    fallback = [t for t in assigned_crews if t not in hard_banned]
    if fallback:
        weights = calculate_weights(...)
    else:
        weights = {t: 1 for t in assigned_crews}

# ...
selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
assigned_crews[selected_truck].append(...)  # ← walker placed here
```

The warning described "placed despite a ban conflict" but was emitted before the actual placement. The fallback unbanned pool was used, and Damien landed on a truck with no banned person — the warning was a false positive.

**The ban data was correct.** Carlos's truck was correctly identified as a hard-banned truck. The problem was that the warning fired when the fallback *path* was entered, not when the walker *actually landed on a banned truck*.

---

## Decision

Move the warning emission to after `selected_truck` is determined. Only emit the warning if the selected truck is in `hard_banned`:

```python
selected_truck = random.choices(truck_ids, weights=truck_weights)[0]
assigned_crews[selected_truck].append({"id": walker.id, "role": "walker"})

# Warn only if the walker genuinely landed on a banned truck.
if selected_truck in hard_banned:
    banned_by = [banner_id for _, banner_id, _ in raw_bans]
    warnings.append({"employee_id": walker.id, "banned_by": banned_by})
```

This changes the semantics of the warning from "this walker entered a ban-constrained code path" to "this walker was actually placed on a truck with a banned crew member."

---

## Consequences

**Positive:**
- Ban conflict warnings now accurately reflect the final dispatch outcome.
- Dispatchers will not investigate false conflicts.
- If the fallback pool successfully avoids all banned trucks, no warning is emitted — which is the correct outcome: the constraint was honored.

**Negative / Tradeoffs:**
- If the fallback pool is fully exhausted (every truck in `assigned_crews` is in `hard_banned`), `weights = {t: 1 for t in assigned_crews}` assigns uniform weights across all trucks including banned ones. In this case `selected_truck in hard_banned` will be true and the warning correctly fires.
- There is a narrow scenario where the ban conflict is recorded with `banned_by = []` (no banner IDs) if `raw_bans` is empty but `hard_banned` is non-empty via `extra_banned_truck_ids`. This edge case is acceptable — the warning still correctly identifies the worker and the conflict truck via the run_dispatch name resolution step.

---

## Broader Principle

When a service function emits a warning, the warning must describe outcome state — the state after the relevant action — not entry state (which code path was entered). This is a specific instance of the general rule: **logging and warnings should be placed as close as possible to the action they describe, and after it, not before.**

This mistake is easy to make because the fallback path and the warning are conceptually linked ("we fell back, therefore there's a conflict"), but the fallback does not always produce a conflict. The distinction between "entered a constrained path" and "produced a constrained outcome" must be explicit in the placement of the side effect.
