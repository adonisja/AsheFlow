# ADR-091: Walker Route Distribution Algorithm

**Date:** 2026-05-17
**Status:** Design confirmed — two open questions blocking implementation (see Blockers)

## Problem

When a driver reaches their anchor point, packages must be divided into walker sub-routes manually by the driver and captain based on pure experience. This is slow, inconsistent, and unscalable. There is no structured tool, no constraint enforcement, and no way to detect misrouted packages before walkers leave the truck.

## Goal

Build an algorithm that:
1. Ingests the truck's package manifest (TBA numbers, tag numbers, bag IDs, addresses — addresses ephemeral)
2. Pairs OV packages to their accompanying totes via Sort Zone → bag ID
3. Groups packages into geographic clusters using delivery addresses, one cluster per walker
4. Enforces cart constraints (6 tote slots max, OV size-based displacement)
5. Flags misrouted packages (packages whose address doesn't match their tote's cluster)
6. Discards all address data immediately after sort — output contains TBA + tag numbers only
7. Applies a difficulty modifier to determine trip structure per walker
8. Outputs mobile-optimized route cards per walker and a full web view for dispatch/captain
9. Collects outcome data to eventually recommend optimal walker counts per route

---

## Data Model

### Package identifiers
- **TBA number** — Amazon's primary package identifier, available in Cortex. Primary key in all output.
- **Tag number** — unique yellow physical tag on the package, associated in Amazon Flex but NOT in Cortex. Secondary identifier used by field staff to physically locate packages.
- **Bag ID** — color + label number (e.g. Green 5270). Identifies which tote a package is physically in.

### Address data (ephemeral — see Legal section)
- Full delivery address per package assumed accessible in bulk at sort time
- Used ONLY during the algorithm run — never persisted to database, logs, or UI output
- Algorithm outputs TBA + tag number groupings only — no addresses in any stored artifact

### OV (Oversized) Packages
- Staged separately at the warehouse
- **OV Sort Zone code = warehouse staging locator only** — tells driver where in the station to find the OV and which tote it accompanies. NOT geographic.
- Bag label listed next to Sort Zone = the tote the OV is paired with (same row = paired)
- OVs travel with their paired tote → assigned to the same walker automatically
- OV size tier (XL/L/M/S) available from Cortex

### Bag Labels
- Color = physical tote bag color
- Number = label ID
- Purely identifiers — no geographic or zone information embedded

### Zone Codes
- **Not used as geographic primitives**
- OV Sort Zones = warehouse locators only (confirmed — not geographic)
- Full delivery addresses replace zone codes as the geographic input entirely

---

## Legal / Privacy Model

### Approach: Transient processing
Addresses are processed ephemerally — in memory only during the sort, discarded immediately after. This is a recognized legal pattern under CCPA and GDPR:

- **Not stored:** addresses never written to database, disk, logs, or UI
- **Authorized purpose:** route optimization is directly related to the original delivery purpose — not a secondary use
- **Authorized processor:** DSP is already an authorized data processor for these deliveries under the Amazon contract
- **Output is clean:** TBA numbers and tag numbers only — no addresses in any stored artifact, no way to reconstruct customer location from output

### What reduces legal exposure:
1. In-memory only — ephemeral, not persisted
2. Time-bounded — single sort operation, data gone after
3. Output contains no PII — TBA + tag number only
4. Processing purpose = delivery fulfillment (same as Amazon's original purpose)
5. Audit trail records what was sorted, not where it was going

### Remaining legal prerequisite (MUST confirm before building):
Does the Amazon DSP agreement authorize bulk address access for operational optimization purposes beyond the Rabbit app? The transient processing argument is sound, but the **source** of the bulk address data must be contractually authorized. Confirm with Amazon Business Coach before implementing the address ingestion layer.

---

## Data Sources

### From Amazon Cortex (manifest)
- Per-package: TBA number, bag ID, delivery address (ephemeral)
- OV packages: Sort Zone code, size tier (XL/L/M/S), paired bag ID
- Route ID, dispatch time, duration estimate

### From AsheFlow dispatch system
- Confirmed field staff per truck (walkers, trainers, trainees)
- Walker count inferred from confirmed assignments (excludes driver), dispatcher can override
- Difficulty flags per location block (cold-start: all Standard)

### NOT available (PII / ToS constraints)
- Persistent storage of customer addresses — PII constraint, never stored
- Amazon Rabbit app data stream — ToS constraint
- Write access to Amazon Flex — no API exists

---

## Open Questions / Blockers

### BLOCKER 1 — Bulk address access authorization (Q1)
**Question:** Does the Amazon DSP agreement authorize bulk address access for operational optimization purposes beyond the Rabbit app?

**Impact:** Legal prerequisite for the address ingestion layer. The transient processing model is sound, but the data source must be contractually authorized before building.

**Status:** Must confirm with Amazon Business Coach before implementation.

### BLOCKER 2 — Cortex data feed format (Q2)
**Question:** What is the exact Cortex data feed format for per-package data (TBA number, bag ID, address)?

**Impact:** Determines ingestion layer implementation — file format, API pull, or other mechanism.

**Status:** Research / confirm with Amazon.

---

## Cart Constraint Model

A single walker cart holds a maximum of 6 tote slots. OV packages displace tote slots based on size:

| OV Size | Totes Displaced |
|---|---|
| XL | 2–3 |
| L | 2–3 |
| M | 1–2 |
| S | 1 |

Conservative (lower) displacement value used as default; dispatcher can override.
OV displacement is inherited by whichever walker receives the paired tote.

**Cart capacity formula:**
```
available_tote_slots = 6 - sum(OV displacements on this cart)
```

---

## Difficulty Model (Cold Start)

Every location block starts at **Standard**. Captains/dispatchers flag manually over time.

| Tier | Trips per cart | Example |
|---|---|---|
| Standard | 1 | Normal residential block |
| Moderate | 2 | Large walkup building |
| Heavy | 3+ | High-rise, no elevator, many floors |

Flags persist and build location difficulty profiles over time. Eventually feeds walker count recommendations.

`block_key` (e.g. `38th_St_400_W`) is derived from the address at sort time and stored as an opaque key — not the raw address. Difficulty flags persist without storing PII.

---

## Walkers / Field Staff

- Mix of roles per truck: driver (1, excluded from delivery), trainers, walkers, trainees
- Min ~7, max ~14 field staff doing deliveries
- Dispatcher manually inputs walker count per truck; system observes outcomes and eventually recommends optimal count
- All field staff have mobile AsheFlow access; office/dispatch has web access
- Anchor point moves during the day (not fixed)

---

## Trips

- A trip = one full cart load, delivered, returned to anchor point
- Walker returns to truck between trips to be resupplied
- Trip does not always need to be a full cart — difficulty modifier can split into sub-trips
- Sub-trip split determined by difficulty tier of the location

---

## Algorithm Design

### Inputs
```
packages:     list [{tba, tag_number, bag_id, address}]  — address ephemeral
ovs:          list [{sort_zone, size_tier, paired_bag_id}]
walker_count: int (dispatcher input, inferred from dispatch assignments)
difficulty:   dict {block_key: tier}  — default Standard
```

### Phase 1 — OV pairing
- Match each OV to its paired tote via Sort Zone → bag ID (same row on manifest = paired)
- Calculate OV displacement per tote
- Tote effective slot cost = 1 + OV displacement

### Phase 2 — Geographic clustering (address-based)
- Parse each package address → extract street number, street name, block (hundred block), side (odd/even)
- Group packages by geographic proximity:
  - Primary: same street + same hundred block + same side → same cluster candidate
  - Secondary: same street + adjacent hundred block → nearby cluster candidate
  - Tertiary: same street → same broader area
- Target: N clusters where N ≈ walker_count
- Balance clusters by package count (not bag count)
- Totes follow their packages — a tote belongs to whichever cluster holds the majority of its packages

### Phase 3 — Misrouted package detection
- For each package: check if its address matches its tote's cluster
- If a tote contains packages whose addresses span multiple clusters → flag individual packages as misrouted
- Suggest reassignment: move misrouted package's TBA to the cluster matching its address
- If no better cluster exists in today's manifest → flag for captain review
- Output: `[{tba, tag_number, current_bag_id, suggested_cluster}]`
- Addresses NOT included in output — only TBA + tag number + cluster assignment

### Phase 4 — Cart constraint enforcement
- For each cluster: calculate total slot cost (totes + OV displacements)
- If slot cost > 6: split into multiple trips, keeping geographically adjacent totes together
- Apply difficulty modifier to determine sub-trip count per cart load
- Output: ordered trip list per walker

### Phase 5 — Discard addresses
- All address data cleared from memory
- No addresses written anywhere at any point
- Only TBA numbers, tag numbers, bag IDs, and cluster assignments persist

### Phase 6 — Output
```
Per walker (mobile):
  - Trip list (Trip 1, Trip 2, ...)
  - Per trip: bag IDs (color-coded visual), TBA list, tag numbers, package count
  - Difficulty tier + expected sub-trip count
  - Misrouted package alerts (TBA + tag number only)
  - Start Trip / Return buttons

Per captain (mobile):
  - All walkers on truck + current trip status
  - Packages remaining per walker
  - Misrouted package list with one-tap reassignment

Per dispatch (web):
  - Full manifest view
  - Drag-to-reassign packages between walkers
  - Historical outcome data
  - Walker count recommendation (Phase 2+)
```

---

## Data Model (Proposed)

```
WalkerRoute
  id: UUID
  company_id: UUID
  truck_assignment_id: UUID
  route_date: date
  walker_id: UUID
  total_packages: int
  total_bags: int
  total_ovs: int
  planned_trips: int
  actual_trips: int (nullable)
  completed_at: datetime (nullable)
  created_at: datetime

WalkerTrip
  id: UUID
  company_id: UUID
  walker_route_id: UUID
  trip_number: int
  bag_ids: str[]           — color+ID list (e.g. ["Green 5270", "Blue 1134"])
  tba_numbers: str[]       — Amazon package identifiers
  tag_numbers: str[]       — physical yellow tag identifiers
  status: str              — pending | in_progress | completed
  departed_at: datetime (nullable)
  returned_at: datetime (nullable)

LocationDifficultyFlag
  id: UUID
  company_id: UUID
  block_key: str           — e.g. "38th_St_400_W" — derived at sort time, not raw address
  difficulty_tier: str     — standard | moderate | heavy
  flagged_by: UUID
  flagged_at: datetime
  notes: str (nullable)

MisroutedPackageFlag
  id: UUID
  company_id: UUID
  walker_route_id: UUID
  tba_number: str
  tag_number: str
  current_bag_id: str
  suggested_walker_route_id: UUID (nullable)
  resolved: bool
  resolved_by: UUID (nullable)
  resolved_at: datetime (nullable)
```

---

## Implementation Phases

### Phase 1 — Core (build after legal prerequisite confirmed)
- Manifest ingestion: package list with TBA, tag number, bag ID, address (ephemeral)
- OV pairing (Sort Zone → bag ID)
- Address-based geographic clustering
- Misrouted package detection
- Cart constraint enforcement
- Address discard after sort
- Mobile route cards (trip list per walker)
- **Prerequisite:** Confirm Amazon DSP agreement authorizes bulk address access (Q1)

### Phase 2 — Difficulty system
- LocationDifficultyFlag UI (captain/dispatcher flags blocks)
- Trip splitting based on difficulty tier
- Outcome data collection (departed_at, returned_at, actual_trips)
- block_key derivation at sort time (no raw addresses stored)

### Phase 3 — Recommendation engine
- Outcome analytics per route
- Walker count recommendation model
- Confidence scoring

---

## What We Are NOT Building
- Persistent storage of customer addresses (PII constraint)
- Address-level data in any output, log, or UI
- Zone-code-based routing (zone codes are warehouse locators, not geographic)
- Amazon Rabbit app data stream integration (ToS constraint)
- Write access to Amazon Flex (no API exists)
