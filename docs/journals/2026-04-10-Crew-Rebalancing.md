# Journal — Crew Rebalancing After Dispatch

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

After implementing the hard round-robin even-distribution guarantee for each role
(trainers, walkers, trainees) in a prior session, we identified a remaining gap:
per-role round-robin does not guarantee even *total* headcount per truck.

Because each role distributes itself independently, a truck that receives a trainer
early (bumping it to total=2 while others are at total=1) may then attract walkers
via fav-weight compounding — the trainer on that truck might be favored by several
walkers, pulling them all toward the same truck. Even though each role's own
distribution is even, the combined total across roles can diverge significantly.

---

## Problem Discussion

We explored several remedies:

### Option 1: Rotation by last dispatched date
Sort the pool before trimming by how long since each person last worked. Fair for
headcount trimming, but does not address the distribution-within-dispatch problem
and ignores the fav/ban social graph entirely.

### Option 2: Dispatch count equalization
Sort by total lifetime dispatch count. Same limitation — good for trimming fairness,
irrelevant to within-dispatch truck skew.

### Option 3: Unified pass with total-headcount eligibility gate
Replace the four sequential role passes with a single interleaved pass where trucks
are only eligible if their total crew is at or within a tolerance band of the minimum.

**Rejected.** After discussion, this approach was found to fundamentally alter the
role-context model: drivers set the truck's identity, trainers refine it within the
driver context, and walkers/trainees fill into the shaped crew. Collapsing this into
a unified headcount gate means drivers fully determine the social context and
subsequent roles have no meaningful preference signal — they just fill gaps.
Additionally, the approach breaks fav/ban signal at the role-transition boundaries
where it is most valuable (e.g., a walker knowing the trainer is already placed).

### Option 4: Post-assignment rebalancing (chosen)
Keep the four sequential passes exactly as they are — preserving role-context fav/ban
signal — and add a final rebalancing step that corrects egregious imbalances only
after all passes complete.

**Why this works:** At real organizational scale, the social graph is naturally diffuse.
People have different relationships with different subsets of coworkers. A walker who
favors a trainer on Truck A may have no connection to that truck's driver, while also
being favored by the driver of Truck B. The fav/ban network spreads naturally and
snowballing (a single truck attracting all roles through compounding preference) is
extremely rare. When it does occur, it's typically a tight clique (4-8 people who all
mutually fav each other), not a systemic pattern.

Rebalancing handles the edge case without disrupting the 99% of dispatches that
already distribute acceptably.

---

## Implementation

**New file:** `backend/app/services/rebalance_crews.py`

### Algorithm

```
while max_total - min_total > tolerance (default: 2):
    over_truck  = truck with most total members
    under_truck = truck with fewest total members

    candidates = all non-driver members on over_truck
    sort candidates ascending by fav_connection_strength to current crewmates

    for each candidate (weakest first):
        if moving to under_truck violates no hard ban:
            move candidate
            record move
            break
    
    if no candidate could move without ban violation:
        accept imbalance (ban constraints are absolute)
        break
```

### fav_connection_strength

Counts unidirectional and bidirectional fav relationships between the candidate and
their current crewmates. Bidirectional relationships count as 2 (one for each
direction in the `employee_relationships` table). A score of 0 means the person has
no preference signal tying them to the current truck — they are the safest to move.

### Why drivers are excluded from candidates

Drivers are the operational anchor of each truck. Moving a driver post-assignment
would invalidate the preference context that trainers, walkers, and trainees were
placed into. A trainer was placed on Truck 3 partly because that truck's driver
favors them; removing the driver makes that placement meaningless.

### Ban safety

A move is only executed if no hard ban exists between the candidate and any current
member of the destination truck. If every candidate on the over-staffed truck is
ban-blocked from the under-staffed truck, the imbalance is accepted. Ban constraints
are never violated for the sake of headcount balance.

### Tolerance of 2

A spread of 1-2 people between the highest and lowest staffed truck is acceptable
and expected when total employees does not divide evenly by trucks. A tolerance of 2
prevents unnecessary moves while still catching genuine snowball cases.

---

## Integration

`rebalance_crews(assigned_crews, db)` is called in `run_dispatch.py` after the four
role passes and before the DB write. The `assigned_crews` dict is modified in place.
Move records are captured in `rebalance_moves` for potential future logging or
warning output (not currently surfaced to the dispatcher UI).

---

## Files Changed

- `backend/app/services/rebalance_crews.py` — created
- `backend/app/services/run_dispatch.py` — added import and call after role passes
