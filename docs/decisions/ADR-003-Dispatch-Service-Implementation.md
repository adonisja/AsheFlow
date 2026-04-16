# ADR-003: Dispatch Service Implementation Decisions

**Date:** April 6, 2026
**Status:** Accepted

---

## Context

During implementation of the dispatch service functions, several design decisions were made that deviate from or extend the original algorithm design in ADR-002. This ADR captures those decisions.

---

## Decision 1: Per-Truck Assignment Loop (not per-employee)

Drivers, trainers, and walkers are assigned by looping over trucks and picking from the remaining pool — not by looping over employees and picking a truck.

**Reasoning:** Per-truck loop maps naturally to the business mental model ("fill each truck"), creates the illusion of more randomness, and makes future manual manager overrides cleaner — the UI will always ask "who goes on this truck" rather than "where does this employee go."

---

## Decision 2: `assigned_crews` as Shared Mutable State

`assigned_crews = {truck_id: [{"id": employee_id, "role": role}, ...]}` is initialized in `run_dispatch` and passed by reference to all three assignment functions. Each function mutates it in place — no return values needed.

**Reasoning:** Sequential assignment depends on each function seeing the state left by the previous one. Drivers populate `assigned_crews` so trainers can compute fav boosts from driver presence; trainers do the same for walkers. Returning and reassigning would add unnecessary complexity.

**Role stored inline:** Each crew entry stores `{"id": ..., "role": ...}` to avoid N+1 DB queries when role context is needed (e.g. tridirectional check, fan role attribution).

---

## Decision 3: Single Upfront Ban Query Per Assignment Function

Rather than querying bans per employee inside the assignment loop (N queries), each function performs one bulk query for all relevant ban relationships before the loop and builds a lookup dict.

```python
banned_trucks_by_trainer = {}
for ban in ban_records:
    if ban.employee_id in driver_to_truck:
        truck_id = driver_to_truck[ban.employee_id]
        banned_trucks_by_trainer.setdefault(ban.target_employee_id, []).append(truck_id)
    else:
        truck_id = driver_to_truck[ban.target_employee_id]
        banned_trucks_by_trainer.setdefault(ban.employee_id, []).append(truck_id)
```

Inside the loop: `banned_trucks_by_trainer.get(employee.id, [])` is an O(1) dict lookup.

---

## Decision 4: Bidirectional Ban Queries

Bans apply across all roles in both directions — a trainer banning a driver is equivalent to a driver banning a trainer. All ban queries use `or_()` to fetch both directions, then branching logic maps each ban to the correct truck and employee.

**Scope:**
- `assign_trainers`: queries driver-trainer bans (both directions)
- `assign_walkers`: queries all-crew-to-walker bans (both directions, across drivers, trainers, and walkers)

`check_ban.py` was deleted — its logic is now handled inline in both assign functions with the bidirectional query pattern.

---

## Decision 5: Walker Ban Override via Tuple Storage

Walker ban lookups store `(truck_id, offending_walker_id)` tuples instead of just `truck_id`. `offending_walker_id` is `None` for driver/trainer bans (no override possible).

```python
banned_trucks_by_walker.setdefault(ban.target_employee_id, []).append(
    (truck_id, ban.employee_id if ban.employee_id in walker_to_truck else None)
)
```

Inside the loop: `None` offending walker → ban stands immediately. Walker offending walker → `check_ban_override` is called.

**Reasoning:** Override logic requires knowing who issued the ban. Storing the tuple at query time avoids a second lookup at call time.

---

## Decision 6: Two-Pass Even Spread via `first_pass_active` Flag

Trainers (2 per truck minimum) and walkers (1 per truck minimum) use a two-pass approach within a single loop. During the first pass, trucks already at the cap are added to `banned_truck_ids`. The flag is recomputed each iteration.

```python
first_pass_active = any(count < N for count in counts.values())
capped_trucks = [t for t, count in counts.items() if first_pass_active and count >= N]
```

When all trucks reach the minimum, `first_pass_active` becomes `False`, `capped_trucks` is empty, and the second pass begins freely with no state change required.

---

## Decision 7: `employee_role` Added to `calculate_weights` Signature

`calculate_weights` needs to know if the candidate is a walker to decide whether to attempt the tridirectional bonus check. Adding `employee_role: str` as an explicit parameter keeps the function testable and avoids a hidden DB query to look up the role.

`previous_truck_id` was removed from the signature — it was never used in the function body. Consecutive assignment is handled entirely via `check_consecutive_assignment`.

---

## Decision 8: `db.flush()` for Parent-Child Persistence in `run_dispatch`

`TruckAssignment` records are flushed (not committed) immediately after creation so their generated UUID is available for `AssignmentMember` foreign key references within the same transaction.

```python
db.add(truck_assignment)
db.flush()  # get truck_assignment.id before committing
```

A single `db.commit()` at the end persists everything atomically.

---

## Decision 9: Duplicate Dispatch Guard on Router

The `POST /dispatch/` endpoint checks for an existing `TruckAssignment` for today's date before running dispatch. Returns `409 CONFLICT` if one exists.

A caching layer (Redis) is deferred — the DB check is sufficient for now and the cache can be added later without changing dispatch logic.

---

## Consequences

- `assigned_crews` mutation pattern means assignment functions have side effects — callers must be aware
- Walker ban override introduces a recursive call path: `assign_walkers` → `check_ban_override` → `perform_walker_reassignment` → `assign_walkers`. Circular import must be resolved before production
- Trainer priority ordering (driver-fav trainers first per ADR-002) is not yet implemented — trainers are currently assigned in pool order. This is a known gap
- `check_ban.py` deleted — any future use of the standalone bidirectional ban check must be re-extracted if needed
- All-zero weight case (employee banned from every truck) results in flat random assignment and a warning in the response — does not crash dispatch
