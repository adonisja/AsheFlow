# ADR-021: Intra-Truck Trainee Fairness in `assign_trainees`

**Date:** 2026-04-14
**Status:** Accepted

---

## Context

The `assign_trainees` service distributes available trainees across dispatched trainers using a round-robin strategy. The implementation maintained a `paired_counts` dict per trainer and selected only trainers at the current global minimum count, ensuring even distribution across all trainers system-wide.

A production observation revealed that Brandon Hayes (trainer, Truck A) received two trainees while another trainer on Truck A had zero. This is operationally unacceptable: trainees ride on a specific truck, so uneven intra-truck distribution creates a lopsided workload for that truck's crew — one trainer managing two trainees while their truck-mate manages none.

---

## Root Cause

The global minimum check does not enforce fairness within a truck. Consider three trainers — Brandon and Trainer X on Truck A, Trainer Y on Truck B — receiving 4 trainees:

| Trainee | Global min | Eligible | Selected | Counts after |
|---|---|---|---|---|
| 1 | 0 | {Brandon, X, Y} | Brandon | B=1, X=0, Y=0 |
| 2 | 0 | {X, Y} | Y | B=1, X=0, Y=1 |
| 3 | 0 | {X} | X | B=1, X=1, Y=1 |
| 4 | 1 | {Brandon, X, Y} | Brandon | **B=2, X=1, Y=1** |

At step 4, all trainers are at global minimum 1, so all are eligible. Random selection returns Brandon. From a global perspective this is fair; from Truck A's perspective it is not — Brandon is at 2 while X is at 1, both on the same truck.

The specific production sequence was worsened by the continuation pre-pass in `run_dispatch`, which placed a trainee with Brandon before `assign_trainees` ran, giving Brandon an initial count of 1 before the round-robin even started.

---

## Decision

Add a **two-level eligibility check** to `assign_trainees`:

1. **Global minimum (existing):** A trainer is only eligible if their `paired_counts` value equals the current global minimum across all trainers.
2. **Intra-truck minimum (new):** A trainer is only eligible if their `paired_counts` value also equals the minimum count among all trainers on their own truck.

A trainer at the global minimum but above the intra-truck minimum is blocked until their truck-mates catch up.

Implementation in `backend/app/services/assign_trainees.py`:

```python
# Built once before the per-trainee loop:
truck_to_trainers: dict = {}
for t_id, truck_id in trainer_to_truck.items():
    truck_to_trainers.setdefault(truck_id, []).append(t_id)

# Inside the per-trainee loop:
global_min = min(paired_counts.values())

def is_eligible(t_id: object) -> bool:
    if paired_counts[t_id] != global_min:
        return False
    truck_id = trainer_to_truck[t_id]
    truck_mates = truck_to_trainers[truck_id]
    truck_min = min(paired_counts[mate] for mate in truck_mates)
    return paired_counts[t_id] == truck_min

eligible = [t_id for t_id in trainer_ids if is_eligible(t_id)]

# Defensive fallback: if intra-truck constraint produces an empty set (edge
# case: all trainers on every truck are ahead of each other simultaneously,
# which cannot occur in normal operation), relax to global minimum only.
if not eligible:
    eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == global_min]
```

The `truck_to_trainers` reverse map is built once before the loop (O(n) total), not recomputed per trainee. The `is_eligible` inner function captures `paired_counts`, `global_min`, `trainer_to_truck`, and `truck_to_trainers` by closure.

---

## Consequences

**Positive:**
- Brandon cannot receive trainee N+1 while Trainer X, on the same truck, has N-1 or fewer trainees.
- The global fairness guarantee is preserved: no trainer system-wide advances to N+1 until all trainers reach N.
- Truck crews are balanced before cross-truck distribution continues.
- Continuation pre-pass pre-placements are correctly accounted for — any head start a trainer has is visible in `paired_counts` and blocks them under the intra-truck check until their truck-mates catch up.

**Neutral:**
- The fallback path (relax to global min when intra-truck constraint produces empty set) is defensive only and should not fire in normal operation. If it fires, a log warning should be added in a future iteration.

**Trade-off accepted:**
- A trainer on a small truck (1 trainer) is always eligible when at the global minimum — the intra-truck check is a no-op when a trainer has no truck-mates. This is correct behaviour.

---

## Tests

`backend/tests/services/test_assign_trainees.py` — 11 tests:

- `TestBasicPlacement` (4): single trainer, no trainees, no trainers, `paired_trainer_id` always set
- `TestGlobalEvenSpread` (2): 2 trainers different trucks 1 each; 3 trainers 2 trucks even
- `TestIntraTruckFairness` (5): Brandon + X 1 each; continuation pre-pass sends to X; mock-controlled eligible-list verification; 2×2 grid each gets 1; odd count no runaway

All 53 tests passing after fix.
