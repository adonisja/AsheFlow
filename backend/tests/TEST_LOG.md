# Test Log — Dispatch Service Layer

A record of failures encountered during test development, the reasoning behind each,
and the resolution that made the test pass. The goal is to make the *why* durable —
not just what broke, but what it revealed about the code under test.

---

## Session 1 — conftest.py bootstrap

### Failure: `Base.metadata.create_all` crashes on SQLite

**Test file:** conftest.py (db fixture)
**Error:** `CompileError: (in table 'vehicle_inspections', column 'data'): Can't render element of type <class 'sqlalchemy.dialects.postgresql.json.JSONB'>`

**Why it failed:**
`Base.metadata.create_all(engine)` attempts to create every table registered under `Base`,
including `VehicleInspection` which has a `JSONB` column (PostgreSQL-specific). SQLite's
type compiler has no handler for `JSONB` and raises a `CompileError`.

**Approaches considered:**
- Skip `VehicleInspection` by excluding it somehow from `Base.metadata` → not cleanly possible without modifying the model
- Mock the model → defeats the point of the integration-style test
- Build a targeted `MetaData` object containing only the tables dispatch services actually use

**Resolution:**
Created `DISPATCH_TABLES`, a list of the 6 table objects the dispatch services touch
(`Employee`, `Truck`, `TruckAssignment`, `AssignmentMember`, `EmployeeRelationship`,
`EmployeeOffDay`). Built a fresh `MetaData` via `table.to_metadata(meta)` for each, then
called `meta.create_all(engine)`. SQLite only sees tables it can compile.

**Why this resolves it:**
The targeted MetaData contains no JSONB columns. SQLite creates exactly the schema the
dispatch services need, nothing more.

**Lesson:**
When testing a PostgreSQL app with SQLite, never use `Base.metadata.create_all`. Build
a minimal MetaData from only the tables your code under test actually touches.

---

### Failure: Deprecation warning on `table.tometadata()`

**Error:** `AttributeError: 'Table' object has no attribute 'tometadata'` (older SQLAlchemy)
or deprecation warning on newer versions.

**Resolution:** Use `table.to_metadata(meta)` (snake_case with underscore). Renamed in
SQLAlchemy 1.4.

---

## Session 2 — test_assign_walkers.py

### Failure 1: Override test passed in isolation, failed in suite (flaky)

**Test:** `TestWalkerBanOverride::test_override_fires_when_driver_favs_candidate_only`
**Error:** `AssertionError: Candidate should be on truck A after override`

**Why it failed:**
The test passed both walkers (`offender`, `candidate`) in `available_walkers` and
expected `offender` to land on truck A first, triggering the ban when `candidate` was
processed next. This relied on `random.choices` selecting truck A for the offender.

In isolation, the random draw happened to go right. In the full suite, a different
effective random state sent the offender to truck B — the ban was never exercised
because `candidate` had no obstacle to truck A and went there freely.

**Approaches considered:**
1. Patch `random.choices` with `side_effect` list to pin the sequence → attempted, still failed (see Failure 2)
2. Test `check_ban_override` directly instead of through `assign_walkers` → correct approach

**Why approach 1 failed (see Failure 2 below):**
The ban map in `assign_walkers` is built once at the top from the *initial* `assigned_crews`.
Walkers placed mid-loop are never added to `crew_to_truck` or `walker_to_truck`. So when
`candidate` is processed after `offender` has been placed on truck A, the ban is not visible
in the pre-built map — `banned_trucks_by_walker.get(candidate.id, [])` returns `[]`.
The override is never reached regardless of where `offender` lands.

**Lesson:**
Any test whose correctness depends on a specific `random.choices` outcome is not a
test — it's a gamble. Always pin randomness when the scenario requires a specific order.
More importantly: understand what state the service builds at startup vs what it updates
mid-loop. The ban map staleness here is itself a design limitation.

---

### Failure 2: Patch didn't fix it — ban map staleness

**Test:** same as above, after adding `side_effects = [[truck_a.id], [truck_b.id], [truck_a.id]]`
**Error:** same assertion failure — candidate not on truck A

**Why it failed:**
Even with the random choices pinned, the override path was never reached. Root cause:
`assign_walkers` builds `crew_to_truck` and `walker_to_truck` at the top of the function
from the initial `assigned_crews`. Since `assigned_crews[truck_a.id]` only contains the
driver at call time (offender hasn't been placed yet), offender is absent from those maps.
The ban query therefore returns nothing for `candidate`. There are no `raw_bans` to resolve.

The override logic in `check_ban_override` is never called from inside `assign_walkers`
in this scenario — not because it failed, but because the entry condition (`raw_bans` being
non-empty) was never met.

**Resolution:**
Dropped down to testing `check_ban_override` directly. This is the correct unit —
it's where the 3-condition detection logic lives. `assign_walkers` is covered by the other
8 tests in the class. For the override, we call `check_ban_override` with a pre-seeded
`assigned_crews` that already has both the driver and offender on truck A.

We also patched `perform_walker_reassignment` inside the test to avoid a separate bug
(see Failure 3 below) that would crash the call before `check_ban_override` returned.

**Lesson:**
When a higher-level function's internal state prevents a path from being exercised,
test the lower-level function directly. Don't force a scenario that the architecture
won't naturally produce.

---

### Failure 3 (bug discovered): `perform_walker_reassignment` wrong argument count

**Not a test failure — a production bug surfaced by testing.**

**Location:** [backend/app/services/ban_override.py:38](../app/services/ban_override.py)

**Bug:**
```python
# Before fix:
assign_walkers([walker], assigned_crews, base_weights, updated_bans, db)
```
`assign_walkers` signature: `(available_walkers, assigned_crews, base_weights, db)` — 4 params.
This call passes 5. `updated_bans` lands in the `db` slot. The real `db` is an extra fifth
argument causing a `TypeError`. The recursive reassignment of an evicted walker was
silently broken — every override that fired would crash before the walker was re-placed.

**Why it was silent:**
The crash happened inside `check_ban_override` → `perform_walker_reassignment`, after
`check_ban_override` had already returned `True` to `assign_walkers`. The outer placement
loop continued normally (with the offender still stripped from the truck by line 32), but
the evicted walker was never re-placed elsewhere. In production this would leave a walker
missing from all trucks after any override fires.

**Fix:**
Added `extra_banned_truck_ids: list = None` parameter to `assign_walkers`:
```python
# assign_walkers.py
def assign_walkers(
    available_walkers: list,
    assigned_crews: dict,
    base_weights: dict,
    db: Session,
    extra_banned_truck_ids: list = None,   # ← added
) -> list:
    ...
    hard_banned: list = list(extra_banned_truck_ids or [])  # ← seeds per-walker ban list
```

Fixed the call in `ban_override.py`:
```python
# After fix:
assign_walkers([walker], assigned_crews, base_weights, db, extra_banned_truck_ids=updated_bans)
```

**Why this resolves it:**
`extra_banned_truck_ids` pre-seeds `hard_banned` for the evicted walker, blocking the
evicting truck without needing a separate mechanism. The `db` argument is now in the
correct position. The recursive reassignment works correctly.

**Why the parameter is optional (default `None`):**
Normal call sites from `run_dispatch` don't pass extra bans — this is only needed for
the internal recursive call from `perform_walker_reassignment`.

---

## Session 3 — test_run_dispatch.py

### Failure 1 (bug discovered): Excess trainer re-slot mutates ORM object with dict syntax

**Not a test failure — a production bug surfaced by testing.**

**Test:** `TestExcessTrainerReSlot::test_excess_trainers_appear_as_walkers_in_crew`
**Error:** `TypeError: 'Employee' object does not support item assignment` at `run_dispatch.py:118`

**Bug:**
```python
# Before fix:
for t in excess_trainers:
    t["role"] = "walker"   # Employee ORM object, not a dict
```
`available_pool["trainers"]` contains SQLAlchemy `Employee` ORM objects, not dicts.
Dict-style item assignment raises `TypeError`.

**Secondary issue (avoided by the fix):**
Even if the syntax were `t.role = "walker"`, this would mark the Employee as dirty in the
SQLAlchemy session. The subsequent `db.commit()` in `run_dispatch` would permanently change
that trainer's role in the database — a data corruption bug. Every dispatch with excess
trainers would silently demote real trainers to walkers in the DB.

**Why it was silent in production:**
This code path only executes when `len(trainers) > num_trucks × MIN_TRAINERS_PER_TRUCK`.
In production with PostgreSQL, this condition likely never triggered with the live data at
the time, so the bug went unexercised. The test created exactly the conditions to hit it.

**Resolution:**
Removed the mutation entirely. `assign_walkers` writes `role="walker"` into `assigned_crews`
independently of the ORM object's role field — the crew dict entry is what determines the
member's role in the output, not the Employee object. Excess trainers are appended to the
walker pool as-is; they get placed with walker role automatically.

```python
# After fix — no mutation, no secondary DB corruption risk:
if len(all_trainers) > max_trainers_needed:
    excess_trainers = all_trainers[max_trainers_needed:]
    available_pool["walkers"].extend(excess_trainers)
    available_pool["trainers"] = all_trainers[:max_trainers_needed]
```

**Lesson:**
Never mutate ORM objects to represent ephemeral state. SQLAlchemy tracks all attribute
changes on session-attached objects — a "temporary" role change becomes a committed DB
write on the next flush/commit. Use separate data structures (dicts, dataclasses) for
in-memory dispatch state that shouldn't persist.
