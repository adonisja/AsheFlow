# ADR-091: Walker Route Distribution Algorithm

**Date:** 2026-05-17
**Status:** In Progress — two open questions blocking zone-proximity component (see Blockers)

## Problem

When a driver reaches their anchor point, packages must be divided into walker sub-routes manually by the driver and captain based on pure experience. This is slow, inconsistent, and unscalable. There is no structured tool, no constraint enforcement, and no way to detect misrouted bags before walkers leave the truck.

## Goal

Build an algorithm that:
1. Ingests the truck's route manifest (bag labels, zone codes, OV counts)
2. Infers the available walker count from confirmed dispatch assignments
3. Divides bags into walker sub-routes grouped by geographic zone proximity
4. Enforces cart constraints (6 totes + OV displacement rules)
5. Flags misrouted bags (bags whose zone doesn't match their assigned cluster)
6. Applies a difficulty modifier to determine trip structure per walker
7. Outputs mobile-optimized route cards per walker and a full web view for dispatch/captain
8. Collects outcome data to eventually recommend optimal walker counts per route

---

## Data Sources

### From Amazon Cortex (manifest)
- Route ID, dispatch time, duration estimate
- Per-zone: bag labels (color + ID), bag count, OV count
- OV size tier per OV package (XL/L/M/S) — available from Cortex, not printed on sheet
- Zone codes per bag (e.g. `A-27.2W`)

### From AsheFlow dispatch system
- Confirmed field staff per truck (walkers, trainers, trainees)
- Walker count inferred from confirmed assignments (excludes driver)
- Difficulty flags per zone (cold-start: all Standard)

### NOT available (PII / ToS constraints)
- Full delivery addresses — confined to Amazon Rabbit app at stop level
- Per-package address data in bulk — not exposed by Cortex

---

## Open Questions / Blockers

### BLOCKER 1 — Zone code encoding (Q1)
**Question:** What does `A-27.2W` encode exactly? Hypothesis: `A` = zone letter, `27` = street number, `.2` = block segment, `W` = west side. **Unconfirmed.**

**Impact:** Zone proximity calculation depends entirely on this. If confirmed, we can derive street-level adjacency from zone codes alone. If the encoding is different, the proximity model changes.

**Status:** Awaiting confirmation from operations team.

### BLOCKER 2 — Bag-to-zone cardinality (Q2)
**Question:** Does one bag label always correspond to exactly one zone? Or can a single bag contain packages from multiple zones?

**Impact:** If one bag = one zone, misrouted package detection works at the bag level. If bags can span zones, detection requires per-package scanning data we don't have access to.

**Status:** Awaiting confirmation from operations team.

### OPEN ITEM — OV Sort Zone → Bag label relationship
**Question:** Does each OV Sort Zone entry on the manifest correspond to a specific bag label, or are OVs staged separately from totes entirely?

**Impact:** Determines how OVs are assigned to walker routes — whether they follow their bag or are assigned independently.

**Status:** Awaiting answer from Amazon Business Coach.

---

## Cart Constraint Model

A single walker cart holds a maximum of 6 tote slots. OV packages displace tote slots based on size:

| OV Size | Totes Displaced |
|---|---|
| XL | 2–3 totes |
| L | 2–3 totes |
| M | 1–2 totes |
| S | 1 tote |

These ranges will be refined with operational data. Initial implementation uses the conservative (lower) displacement value and allows dispatcher override.

**Cart capacity formula:**
```
available_tote_slots = 6 - sum(displacement per OV on this cart)
remaining_bags = available_tote_slots (after OV assignment)
```

---

## Difficulty Model (Cold Start)

Every zone starts at **Standard** difficulty. Dispatchers and captains can flag zones manually. Flags persist and accumulate over time to build a difficulty profile per zone.

| Tier | Default trips per cart load | Description |
|---|---|---|
| Standard | 1 | Full cart delivered in one trip |
| Moderate | 2 | Cart split into 2 sub-trips (e.g. large walkup) |
| Heavy | 3+ | Cart split into 3+ sub-trips (e.g. high-rise, no elevator) |

Over time, the system will suggest difficulty updates based on observed completion times vs expected duration.

---

## Algorithm Design

### Phase 1 — Input ingestion
```
inputs:
  - manifest: list of bags [{label, color, zone_code, package_count}]
  - ovs: list of OVs [{zone_code, size_tier}]
  - walker_count: int (inferred from dispatch assignments)
  - difficulty_flags: dict {zone_code: tier}
```

### Phase 2 — Zone proximity grouping
Group bags by zone code similarity. Proximity rules (pending Q1 confirmation):
- Same street number (`A-27.x`) = same cluster candidate
- Adjacent street numbers (27, 28) = nearby cluster candidate
- Same zone letter (`A-xx`) = same broader area

Target: produce N zone clusters where N ≈ walker_count, balanced by package count.

### Phase 3 — Cart constraint enforcement
For each cluster:
1. Count totes in cluster
2. Assign OVs from matching zone codes
3. Calculate OV displacement
4. If totes + displacement > 6: split cluster into multiple trips
5. Apply difficulty modifier to determine sub-trip count

### Phase 4 — Misrouted bag detection
For each bag in a cluster:
- If bag's zone code does not match the cluster's dominant zone pattern → flag as misrouted
- Suggest reassignment to the cluster whose zone best matches the bag's zone
- If no better cluster exists in today's manifest → flag for captain review

### Phase 5 — Output generation
Per walker:
- Ordered list of trips
- Per trip: bag labels (color + ID), OV assignments, zone, estimated package count
- Difficulty tier and expected trip count
- Misrouted bag alerts

For captain/dispatch (web):
- Full route breakdown across all walkers
- All misrouted bag flags with suggested reassignments
- Walker count used vs recommended (once recommendation engine has data)

---

## Recommendation Engine (Future — Phase 2)

Collect per-route outcome data:
- Actual completion time per walker
- Packages per walker per hour
- Trips completed vs planned
- Difficulty flags triggered

Over time, build a model that recommends optimal walker count per:
- Total package volume
- Zone mix (difficulty distribution)
- Time of day / route duration

Dispatcher always sees the recommendation but retains manual override. Recommendation confidence displayed alongside suggestion.

---

## Data Model (Proposed)

```
WalkerRoute
  id: UUID
  company_id: UUID
  truck_assignment_id: UUID       — links to existing dispatch assignment
  route_date: date
  walker_id: UUID                 — links to Employee
  zone_cluster: str[]             — zone codes in this walker's assignment
  total_packages: int
  total_bags: int
  total_ovs: int
  difficulty_tier: str            — standard | moderate | heavy
  planned_trips: int
  actual_trips: int (nullable)    — filled post-completion
  completed_at: datetime (nullable)
  created_at: datetime

WalkerTrip
  id: UUID
  company_id: UUID
  walker_route_id: UUID
  trip_number: int
  bag_labels: str[]               — [color+id, ...]
  ov_ids: str[]
  zone_codes: str[]
  status: str                     — pending | in_progress | completed
  departed_at: datetime (nullable)
  returned_at: datetime (nullable)

ZoneDifficultyFlag
  id: UUID
  company_id: UUID
  zone_code: str
  difficulty_tier: str            — standard | moderate | heavy
  flagged_by: UUID                — Employee who set the flag
  flagged_at: datetime
  notes: str (nullable)

MisroutedBagFlag
  id: UUID
  company_id: UUID
  walker_route_id: UUID
  bag_label: str
  bag_zone_code: str              — what the bag says
  assigned_cluster_zone: str      — what cluster it was put in
  suggested_reassignment: str     — zone cluster it should go to
  resolved: bool
  resolved_by: UUID (nullable)
  resolved_at: datetime (nullable)
```

---

## Mobile View (Field)

Walker sees on their device:
- Their name + truck assignment
- Trip list: Trip 1, Trip 2, etc.
- Per trip: colored bag list (visual — matches physical bag color), zone, package count
- "Start Trip" / "Return" buttons (feeds actual_trips and timing data)
- Misrouted bag alert with suggested action

Captain sees on their device:
- All walkers on their truck
- Per walker: current trip status, packages remaining
- Misrouted bag list with one-tap reassignment

---

## Web View (Office/Dispatch)

- Full manifest import (Cortex file upload or API pull)
- Walker count input (pre-filled from dispatch assignments, editable)
- Algorithm output: full route breakdown, drag-to-reassign bags between walkers
- Misrouted flag panel
- Historical outcome data per route (feeds recommendation engine)
- Walker count recommendation (Phase 2)

---

## Implementation Phases

### Phase 1 — Core algorithm + manifest ingestion (build now)
- Manifest upload/parse
- Zone grouping algorithm (zone code proximity — pending Q1/Q2 confirmation)
- Cart constraint enforcement
- Misrouted bag detection
- Walker route + trip output
- Mobile route cards

### Phase 2 — Difficulty system
- ZoneDifficultyFlag model + UI
- Trip splitting based on difficulty tier
- Outcome data collection (departed_at, returned_at, actual_trips)

### Phase 3 — Recommendation engine
- Outcome analytics
- Walker count recommendation model
- Confidence scoring

---

## What We Are NOT Building
- Address-level stop sequencing (PII constraint — addresses only in Amazon Rabbit app)
- Integration with Amazon Rabbit app data stream (ToS constraint)
- Write access to Amazon Flex (no API exists)
