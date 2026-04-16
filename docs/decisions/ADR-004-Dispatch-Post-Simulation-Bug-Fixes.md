# ADR-004: Dispatch Post-Simulation Bug Fixes

**Date:** April 6, 2026
**Status:** Accepted

---

## Context

After implementing the dispatch service functions (ADR-003), five simulation scenarios were run to identify gaps, conflicts, and edge cases. Four bugs were found and fixed. This ADR documents each bug, its root cause, and the fix applied.

---

## Bug 1: Fan Boosts Applied to Banned Trucks

**File:** `services/calculate_weights.py`

**Root cause:** The ban zeroing pass and the fan boost pass were independent loops. A truck zeroed in the first loop could receive a role boost or mutual bonus in the second loop, resulting in a non-zero weight for a banned truck.

**Example:** Walker W is banned from Truck-1 by a driver. `base_weights_copy[Truck-1] = 0` after ban pass. But Driver D on Truck-1 has W on their fav list — the fan boost loop adds `0 * ROLE_BOOST + MUTUAL_BONUS["bidirectional"]` = `0.10` to Truck-1. Banned truck now has weight `0.10`.

**Fix:** Filter `fans_by_role[role]` to `eligible_trucks` before any boost logic:
```python
eligible_trucks = list(set(t for t in fans_by_role[role] if t not in banned_truck_ids))
```
Banned trucks are excluded entirely from the fan boost pass.

---

## Bug 2: Double Boost from Multiple Fans of Same Role on Same Truck

**File:** `services/calculate_weights.py`

**Root cause:** `fans_by_role[role]` was built by appending a truck ID once per fan. If two trainers on the same truck both fav the candidate, the same truck ID was appended twice. `len(fans_by_role["trainer"]) > 1` triggered the conflict branch incorrectly, and the split `ROLE_BOOST / n` was applied twice to the same truck.

**Example:** Truck-1 has T1 and T2, both fav Candidate C. `fans_by_role["trainer"] = [Truck-1, Truck-1]`. Conflict branch fires. Split = `ROLE_BOOST / 2`. Loop applies split to `Truck-1` twice → double boost.

**Fix:** The `set()` in the `eligible_trucks` filter (Bug 1 fix) also resolves this — deduplication ensures a truck appears at most once per role regardless of fan count.

---

## Bug 3: Walker Ban Tuples Missing Banner ID for Driver/Trainer Bans

**File:** `services/assign_walkers.py`

**Root cause:** The ban tuple originally stored `(truck_id, offending_walker_id_or_None)` where `None` represented a driver/trainer ban. When building the `banned_by` list for warnings, `None` values were included instead of the actual banner employee IDs.

**Fix:** Changed tuple structure to `(truck_id, banner_id, is_walker)`:
- `banner_id` is always the ID of the employee who issued the ban
- `is_walker` boolean flag determines override eligibility
- Warning collection: `banned_by = [banner_id for _, banner_id, _ in raw_bans]`

---

## Bug 4: No Pool Size Validation Before Driver Assignment

**File:** `services/run_dispatch.py`

**Root cause:** `assign_drivers` loops over trucks and picks from `remaining_drivers`. When `remaining_drivers` is exhausted before all trucks are filled, `random.choices([], weights=[])` raises `IndexError` — an unhandled exception that bypasses the router's `except ValueError` block and returns `500`.

**Business context:** Fewer drivers than trucks indicates missing slots that require manual assignment by a manager. This is a known operational scenario, not a system error.

**Fix:** Validate pool size in `run_dispatch` before calling `assign_drivers`:
```python
if len(available_pool["drivers"]) < len(truck_ids):
    missing = len(truck_ids) - len(available_pool["drivers"])
    raise ValueError(
        f"Insufficient drivers: {len(available_pool['drivers'])} available for {len(truck_ids)} trucks. "
        f"{missing} slot(s) require manual assignment before dispatch can run."
    )
```
Router surfaces this as `400 BAD REQUEST` with the descriptive message.

---

## Additional Finding: All-Zero Weights (Not a Crash — Handled)

When a trainer or walker is banned from every truck (by drivers/trainers on each truck), `calculate_weights` returns all-zero weights. Rather than crashing, `assign_trainers` and `assign_walkers` detect this condition, reset weights to flat `[1] * n`, and append a warning entry:

```python
{"employee_id": <id>, "banned_by": [<banner_ids>]}
```

Warnings are collected in `run_dispatch` and returned to the caller. The router includes them in the response under a `warnings` field. This flags the employee for management review without halting dispatch.

---

## Consequences

- `calculate_weights` now correctly excludes banned trucks from all boost logic — weight ordering is: ban zero → consecutive penalty → fan boost (eligible only)
- Warning system added to `assign_trainers`, `assign_walkers`, `run_dispatch`, and the dispatch router — all-zero weight cases surface to the caller rather than failing silently
- Driver pool validation converts a runtime `IndexError` into a meaningful `400` response
- Tuple structure change in `assign_walkers` is a breaking change to the internal ban representation — any future code reading `banned_trucks_by_walker` must unpack 3 values
