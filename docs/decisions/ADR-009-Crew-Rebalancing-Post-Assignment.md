# ADR-009 — Post-Assignment Crew Rebalancing

**Date:** 2026-04-10  
**Status:** Accepted  
**Author:** adonisja

---

## Context

The dispatch algorithm assigns employees to trucks in four sequential role passes:
drivers → trainers → walkers → trainees. Each pass uses a hard round-robin constraint
(only trucks at the current minimum count for that role are eligible) combined with
fav/ban weighted random selection within the eligible set.

This guarantees even distribution *per role* but does not guarantee even *total*
headcount per truck. Because roles are distributed sequentially and fav-weight
compounding is an intentional feature, a truck can legitimately accumulate more total
members than others if fav connections compound across role transitions.

Example: Truck A gets a driver, then attracts a trainer who favors that driver, then
attracts walkers who favor that trainer. Each individual placement is correct under
the algorithm's rules, but Truck A ends up with 7 people while Truck B has 4.

---

## Decision Drivers

1. **The fav/ban preference system is non-negotiable.** It is a core feature designed
   to improve worker satisfaction, reduce tardiness, and reduce truancy. Any solution
   that weakens preference signal in the normal case is unacceptable.

2. **Role-context must be preserved.** The sequential pass order (driver → trainer →
   walker → trainee) is meaningful. Each role is placed knowing who came before, which
   allows preference relationships to carry context (e.g., a walker choosing based on
   which trainer is already on the truck). Collapsing this into a unified headcount
   pass destroys that signal.

3. **At organizational scale, snowballing is rare.** Social graphs are naturally
   diffuse. Even popular employees have fans spread across different trucks because
   those fans have separate relationships of their own. A pathological clique (all 8
   people mutually fav each other) is the exception, not the rule.

4. **The fix should be proportional to the problem's frequency.** Most dispatches
   already distribute acceptably. The solution should be a safety net for edge cases,
   not a restructuring of the core algorithm.

---

## Options Considered

### Option A: Unified pass with total-headcount eligibility gate

Replace the four role passes with a single interleaved pass. A truck is only eligible
for any new member if its total crew count is within a tolerance band of the minimum.

**Rejected.** This makes total headcount the primary constraint and role-context
secondary. After drivers are placed, a trainer with fans across multiple trucks can
no longer freely express preferences — they are gated by which trucks happen to be
numerically behind. Walkers placed after trainers have even less signal. Drivers
effectively become the sole determinant of truck identity, with subsequent roles
filling gaps rather than expressing preferences. This defeats the core design goal.

### Option B: Tolerance band variant of Option A

Allow trucks within `min + 1` to be eligible, softening the gate.

**Rejected** for the same structural reason. The problem is not the strictness of the
gate; it is that headcount becomes the primary filter, demoting preference signal
regardless of tolerance value.

### Option C: Post-assignment rebalancing (chosen)

After all four passes complete, inspect total crew sizes. If any truck exceeds the
minimum by more than a configurable tolerance (default: 2), move the weakest-linked
member from the over-staffed truck to the most under-staffed truck.

**Accepted.** This approach:
- Does not touch the sequential pass structure
- Does not weaken preference signal during assignment
- Only corrects imbalances that actually exist after the fact
- Preserves ban constraints absolutely (a move that would create a ban conflict is skipped)
- Fires zero or one times in the overwhelming majority of dispatches

---

## Decision

Implement `rebalance_crews()` as a post-assignment safety net. The function:

1. Computes total crew size per truck after all four passes.
2. Iterates while `max_total - min_total > tolerance`.
3. On each iteration, identifies the most over-staffed and most under-staffed trucks.
4. Scores non-driver members of the over-staffed truck by their fav connection
   strength to current crewmates (count of fav relationships in either direction).
5. Attempts to move the weakest-linked member (lowest score) to the under-staffed
   truck, skipping moves that would violate any hard ban.
6. If no member can be moved without a ban violation, accepts the imbalance.

Drivers are never candidates for relocation. They define the operational and social
context into which all other roles were placed.

---

## Consequences

**Positive:**
- Maximum crew spread bounded to `tolerance` (default 2) in normal cases
- No change to preference satisfaction in the 99% of dispatches without snowballing
- Existing fav/ban/consecutive/bidirectional/tridirectional logic is entirely unaffected
- Ban constraints remain absolute

**Negative:**
- In rare edge cases, the weakest-linked member of a clique is relocated, which
  slightly reduces their preference satisfaction for that dispatch
- If the entire over-staffed truck's non-driver members are ban-blocked from the
  under-staffed truck, the imbalance persists (ban correctness takes priority)
- Adds one additional DB query pass (fav relationship lookup per candidate scored)
  which is negligible at dispatch scale

---

## Tolerance Value

The default tolerance of 2 was chosen because:
- A spread of 1 is expected and unavoidable when total employees does not divide
  evenly by number of trucks
- A spread of 2 is acceptable operational variance
- A spread of 3+ indicates compounding bias that warrants correction

The tolerance is a parameter and can be adjusted per-call if operational requirements
change.
