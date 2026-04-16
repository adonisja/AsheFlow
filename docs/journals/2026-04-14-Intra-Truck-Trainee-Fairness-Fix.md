# Journal: Intra-Truck Trainee Fairness Fix and Test Suite Expansion
**Date:** 2026-04-14

---

## Goal for the Session

Investigate why trainer Brandon Hayes received two trainees while other trainers on the same truck had zero, then fix and test the root cause.

---

## Root Cause Analysis

### The reported symptom
Brandon Hayes (trainer, Truck A) had two trainees assigned. Other trainers on Truck A had zero. This should be impossible — the intent of `assign_trainees` is round-robin distribution.

### The bug

`assign_trainees` used a global round-robin across all trainers regardless of truck. Eligibility was:

```python
min_count = min(paired_counts.values())          # global minimum
eligible  = [t for t, cnt in paired_counts.items() if cnt == min_count]
```

This does spread trainees evenly across all trainers globally. But it does not enforce that trainers on the same truck reach equal counts before any of them advance to a higher count.

**Concrete failure sequence** — 3 trainers (Brandon + Trainer X on Truck A, Trainer Y on Truck B), 4 trainees:

| Trainee | Global min | Eligible | Selected | Counts after |
|---|---|---|---|---|
| 1 | 0 | {Brandon, X, Y} | Brandon | B=1, X=0, Y=0 |
| 2 | 0 | {X, Y} | Y | B=1, X=0, Y=1 |
| 3 | 0 | {X} | X | B=1, X=1, Y=1 |
| 4 | 1 | {Brandon, X, Y} | Brandon | **B=2, X=1, Y=1** |

After trainee 2, Trainer X on Truck A had zero while Trainer Y on Truck B had one. The global round-robin correctly filled X next. But once all trainers were at 1, the cycle returned to Brandon before the truck-level balance had a reason to prefer X.

The specific production scenario involved a continuation-request pre-pass in `run_dispatch` placing a trainee with Brandon before `assign_trainees` ran. Brandon started at 1, X and Y at 0. The global round-robin then filled X and Y before returning to Brandon — but with certain trainee-to-trainer ratios, it returned to Brandon before X had received a second trainee, even though they share a truck.

---

## The Fix

Added a two-level eligibility check in `assign_trainees`:

```python
# truck_id -> [trainer_ids on that truck] — built once before the loop
truck_to_trainers: dict = {}
for t_id, truck_id in trainer_to_truck.items():
    truck_to_trainers.setdefault(truck_id, []).append(t_id)

def is_eligible(t_id) -> bool:
    if paired_counts[t_id] != global_min:
        return False
    truck_id   = trainer_to_truck[t_id]
    truck_mates = truck_to_trainers[truck_id]
    truck_min  = min(paired_counts[mate] for mate in truck_mates)
    return paired_counts[t_id] == truck_min

eligible = [t_id for t_id in trainer_ids if is_eligible(t_id)]

# Defensive fallback: relax to global minimum only if intra-truck constraint
# produces an empty eligible set (shouldn't happen in normal operation).
if not eligible:
    eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == global_min]
```

A trainer is now only eligible if:
1. Their count equals the global minimum (existing), AND
2. Their count equals the minimum count among all trainers on their truck (new)

Brandon cannot receive trainee N+1 while Trainer X, on the same truck, has N-1 or fewer.

---

## Tests Written

New file: `backend/tests/services/test_assign_trainees.py` — 11 tests across 3 classes.

### `TestBasicPlacement` (4 tests)
- Single trainer receives all trainees
- No trainees → no change, empty return
- No trainers → no placements (early-return path)
- `paired_trainer_id` tag is always set on every placed trainee

### `TestGlobalEvenSpread` (2 tests)
- 2 trainers on different trucks, 2 trainees → 1 each
- 3 trainers across 2 trucks, 3 trainees → 1 each, no truck-mate gets 2 while other has 0

### `TestIntraTruckFairness` (5 tests) — the core regression tests
- Brandon + Trainer X, 2 trainees → exactly 1 each (base case)
- Continuation pre-pass pre-loads Brandon → pool trainee must go to Trainer X
- Mock-controlled test that Brandon is absent from the eligible list when his count exceeds his truck-mate's (direct intra-truck gate verification)
- 2 trucks × 2 trainers, 4 trainees → each trainer receives exactly 1
- Odd count (3 trainees, 2 trainers): neither trainer gets 2 while the other has 0

---

## Tests Updated: `test_assign_walkers.py`

Two pre-existing tests were failing due to earlier fixes that weren't reflected in the tests:

### `test_override_fires_when_driver_favs_candidate_only`
`check_ban_override` was fixed to always return a `(bool, truck_id | None)` tuple. The test was asserting `result is True` (scalar). Updated to `overridden, reassigned_to = result; assert overridden is True`.

### Fallback warning test
The old test (`test_fallback_emits_warning_when_all_minimum_trucks_hard_banned`) set up truck B as above-minimum with a pre-placed walker, then banned the walker from truck A. After the ban-warning timing fix (ADR-019), the warning only fires when the walker *lands on* a banned truck. Since the walker lands on truck B (unbanned), no warning fires — which is now correct.

**Old test** was renamed and restructured into two tests:

1. `test_fallback_emits_warning_when_walker_placed_on_banned_truck` — both trucks have drivers who ban the walker, so ALL trucks are hard-banned. The walker must land on a banned truck. Warning fires. This is the genuine "could not avoid the ban" scenario.

2. `test_no_warning_when_fallback_avoids_banned_truck` — truck A is banned (only minimum truck), truck B is unbanned (above minimum). Walker is placed on truck B. No warning. This locks in the correct ADR-019 behavior: successfully avoiding a ban does not produce a warning.

---

## Final Test Count

| File | Tests | Status |
|---|---|---|
| `test_assign_trainees.py` | 11 | All new |
| `test_assign_walkers.py` | 10 (+1 split) | 2 updated, 1 added |
| `test_assign_trainers.py` | 9 | Unchanged |
| `test_calculate_weights.py` | 14 | Unchanged |
| `test_run_dispatch.py` | 9 | Unchanged |
| **Total** | **53** | **53 passed** |
