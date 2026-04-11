# ADR-002: Dispatch Algorithm Design

**Date:** April 5, 2026
**Status:** Accepted — revised April 5, 2026 (trainer sequencing, walker single-pass, bi/tri boost integration)

---

## Context

The core feature of AsheFlow Dispatch is the daily truck assignment algorithm. Each day, a dispatcher triggers the algorithm which assigns available employees to active trucks. The algorithm must respect hard constraints, apply soft preferences, and produce a complete crew manifest for each truck.

This ADR captures the design decisions made before implementation began.

---

## Algorithm Inputs

| Input | Source | Notes |
|---|---|---|
| `date` | Auto (today) or dispatcher override | Defaults to current date |
| `truck_ids` | Dispatcher selection | Which trucks are running today |
| `walkers_per_truck` | Dispatcher input | Fixed count, same for all trucks |

Real-world note: date override is theoretically available but practically unused — the number of trucks and walkers depends on package volume data that only arrives the day of. Logged in `discussion.md` as confirmed business constraint.

---

## Hard Constraints (disqualify entirely)

1. **Off day** — employee is off today → excluded from available pool
2. **Ban list** — two employees with a mutual ban cannot appear on the same truck

---

## Soft Constraints (weighted preference)

3. **Consecutive truck** — employee should not be assigned to the same truck as their most recent prior assignment. Strong preference, not a hard block — on low-volume days a full crew takes priority over this rule. Penalty weight: 0.05 (subject to tuning).
4. **Fav list** — employees on each other's fav list receive a probability boost to land on the same truck. Boost magnitude and multipliers defined in ADR-001.

---

## Fill Order

```
1. Select trucks for the day (dispatcher input)
2. Build available pool per role (remove employees who are off today)
3. Assign drivers — pure random, one per truck
4. Assign trainers — sequential weighted assignment (see below)
5. Assign walkers — single weighted roll per walker
```

Drivers are assigned first because they have an earlier notification window and earlier confirmation close time than trainers and walkers.

---

## Driver Assignment

Pure random from available driver pool. No weighting — drivers are independent of each other (one per truck). Each driver placed immediately populates that truck's weight contribution for subsequent trainer and walker rolls.

---

## Trainer Assignment — Sequential Weighted with Live Weight Updates

Trainers are NOT assigned simultaneously. They are assigned **one at a time**, in priority order, with the weight table updated after each placement.

**Why not simultaneous:** A trainer with only a trainer fav (no driver fav) has no truck anchor until another trainer they fav is placed. Simultaneous rolling cannot resolve this — sequential assignment allows each placement to inform the next.

**Priority order:**
1. Trainers with at least one driver fav — strongest anchor, roll first
2. Trainers with only trainer favs — roll after pass 1 trainers are placed; by then their fav trainer may already be on a truck
3. Trainers with no favs or no resolved anchors — flat random roll

**Weight calculation per trainer per truck:**
- Base weight: `1.0` for all trucks (neutral starting point)
- Apply driver fav boosts (from already-assigned drivers' fav lists)
- Apply trainer fav boosts (from already-assigned trainers' fav lists)
- Apply bi/tri-directional multipliers where mutual favs exist (see ADR-001)
- Apply consecutive truck penalty (0.05) if this truck was their last assignment
- After each trainer is placed, recalculate weights for all remaining unassigned trainers

**Key insight:** By the time a low-priority trainer (trainer-fav-only or no-fav) is rolled, the weight table may already be non-neutral due to other trainers having been placed and pulling weights. Priority order ensures maximum information is available before the flat-roll fallback kicks in.

---

## Walker Assignment — Single Weighted Roll

Walkers receive a **single weighted roll** across all trucks. By the time walkers are assigned, every truck already has a driver and two trainers — the weight table is fully populated.

**Why no sequential priority for walkers:**
1. Walkers have minimal influence on crew composition by design — they fill remaining slots
2. Drivers and trainers already carry the structural weight of the assignment; walker favs are supplementary
3. The fully populated weight table from driver and trainer placements already pulls walkers toward preferred trucks naturally

**Weight calculation per walker per truck:**
- Base weight: `1.0`
- Apply boosts from any driver or trainer on that truck who has this walker in their fav list
- Apply this walker's own fav boosts toward trucks containing their fav driver/trainer/walker
- Apply bi/tri-directional multipliers where mutual favs exist
- Apply consecutive truck penalty (0.05) if applicable
- Ban check after selection — re-roll if conflict found

---

## Consecutive Truck Check (corrected design)

The check must look at the employee's **most recent actual assignment**, not calendar yesterday.

**Why:** If Marcus worked Monday on Atlas, was off Tuesday, and returns Wednesday — checking `date == yesterday` finds nothing (Tuesday had no assignment). He could incorrectly be placed on Atlas again.

**Correct approach:** Query `truck_assignments` joined to `assignment_members`, filter by `employee_id`, order by `date DESC`, take `.first()`. If that result's `truck_id` matches the current truck, apply the 0.05 soft penalty weight instead of 1.0 base.

**Implementation note:** `check_consecutive_assignment()` in `services/dispatch.py` has been updated to reflect this — the original `date == yesterday` logic has been removed.

---

## Ban Enforcement

After each weighted selection, run `check_ban_relationship()` against all crew members already on the selected truck. If a conflict is found:
1. Remove candidate from the available pool for this truck
2. Re-roll from the updated weight table
3. Repeat until valid candidate found or pool exhausted
4. If pool exhausted: log warning, truck may be understaffed for this role

---

## Weight Table Summary

**Initial base weight per truck** is dynamic — calculated from the number of active trucks:
```
base_per_truck = 1.0 / num_trucks
# e.g. 5 trucks → 0.20 per truck (equal 20% probability each)
```

Adjustments are applied on top of this base in order:

| Condition | Effect |
|---|---|
| Ban conflict | truck weight → 0.0 (hard block) |
| Consecutive truck penalty | truck weight × 0.05 (strong discouragement) |
| One-directional fav boost | truck weight + (base × role multiplier) |
| Bi-directional mutual fav | truck weight + (base × role multiplier × 1.2), cap 0.85 |
| Tri-directional mutual fav | truck weight + (base × role multiplier × 1.3), cap 0.85 |

**Example with 5 trucks, no bans or favs:**
All trucks start at 0.20 — pure random assignment.

**Example with 5 trucks, one ban, one consecutive penalty:**
- Banned truck: 0.0
- Consecutive truck: 0.20 × 0.05 = 0.01
- Remaining 3 trucks: 0.20 each (weights normalized by `random.choices`)

**Interaction between fav pull and consecutive penalty:**
If a candidate's fav driver is on the same truck as their previous assignment, the fav boost still applies — the consecutive penalty is a soft discouragement, not a hard block. The fav pull may outweigh the penalty, which is intentional: most employees will not mind or may prefer working with their fav again.

---

## Open Questions

- **Q1 (logged in discussion.md):** Are there cases where a specific driver must be pinned to a specific truck (e.g. a manager filling in)? Currently: random assignment. Action: confirm with business.
- **Q2:** Consecutive truck penalty weight of 0.05 is an initial estimate — needs tuning after a trial period.
- **Q3:** Base boost weights (0.70/0.50/0.30) and multipliers (1.2×/1.3×) need business validation after observing real dispatch outcomes.

---

## Consequences

- `dispatch.py` service will be significantly more complex than other services — it orchestrates multiple queries, sequential weight calculations, conflict resolution, and ban checks in a single operation.
- `check_consecutive_assignment()` has been corrected — old `date == yesterday` logic removed.
- Base weights and multipliers must be extracted to a constants file — not hardcoded inline — so tuning requires changing one value, not hunting across the codebase.
- The weighted assignment system should be unit tested with mock data before wiring into the API.
- The algorithm produces a full set of `TruckAssignment` and `AssignmentMember` records — same models already built, no schema changes needed.
- Sequential trainer assignment means the algorithm is not trivially parallelizable — this is acceptable at current scale.
