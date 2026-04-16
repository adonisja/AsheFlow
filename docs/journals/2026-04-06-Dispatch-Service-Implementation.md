# Engineering Journal: April 6, 2026

**Session Start Time**: April 6, 2026, ~12:00 AM EST (GMT-5, NYC)
**Session End Time**: April 6, 2026, 2:49 AM EST (GMT-5, NYC)

## Goal for the Session
Implement the dispatch service helper functions bottom-up, following the dependency order established in ADR-002.

---

## Functions Completed This Session

### `get_available_pool` (`services/available_pool.py`)
- Single query with `.exists()` subquery to exclude employees with off days today
- Groups results by role in Python — one DB round-trip
- Added `Employee.is_active == True` filter (missing factor caught during review)
- Accepts `target_date: date = None`, defaults to `date.today()`

### `get_base_weights` (`services/base_weights.py`)
- Returns `{truck_id: 1/n}` for n trucks
- Guards against empty list with `ValueError` — service layer raises Python exceptions, not HTTPException

### `get_fav_list` (`services/fav_list.py`)
- Returns `{"drivers": [], "trainers": [], "walkers": []}` of target employee IDs
- Uses JOIN + tuple unpacking `(relationship, role)` to get target role in one query
- Consistent list return for all roles (even single-limit roles) — empty list safer than None

### `perform_bidirectional_check` (`services/bidirectional.py`)
- Single query with `or_()` fetching both directional rows, `.count() == 2` confirms mutual
- `or_()` finds either row; count enforces both exist — AND logic lives in the count

### `perform_tridirectional_check` (`services/tridirectional.py`)
- All 6 directional pairs listed in `or_()`, `.count() == 6` confirms full triangle
- Parameters named `driver_id`, `trainer_id`, `walker_id` — role-specific by design

### `resolve_conflict` (`services/resolve_conflict.py`)
- Takes `candidate_id` and `conflict_ids: list[(truck_id, crew_member_id)]`
- Builds `fav_ids` set from candidate's fav list, checks membership in one pass
- Returns winning `truck_id` or `None` if no mutual match

### `check_consecutive_assignment` (moved to `services/previous_assignment.py`)
- Corrected from `date == yesterday` to most-recent-assignment query
- Moved to own file for modularity

### `get_fans` (`services/fans_list.py`)
- Reverse of `get_fav_list` — finds crew members who fav the candidate
- Builds `crew_to_truck` reverse lookup for O(1) truck attribution
- Single query with `.in_()` on all crew IDs
- Returns `{truck_id: [crew_member_ids_who_fav_candidate]}`
- Uses `setdefault()` for clean dict grouping

### `calculate_weights` (`services/calculate_weights.py`) — COMPLETE
- Full weight calculation: ban zeroing, consecutive penalty, role boost, conflict resolution, bi/tri-directional bonus
- `employee_role: str` added to signature — needed to decide tridirectional vs bidirectional path
- `previous_truck_id` removed — unused parameter, consecutive check handles this via DB query
- `boosted_truck_id = None` initialized per role iteration — prevents NameError when no fans exist
- Conflict resolution: winner gets full `ROLE_BOOST`; no winner splits `ROLE_BOOST / n` evenly
- Bi/tri bonus only applies when a single boosted truck exists (not in the split case)
- Tridirectional: walkers only, requires driver + trainer already on truck, falls back to bidirectional if fails
- `fans_by_truck[boosted_truck_id][0]` used for bidirectional fan_id — not the loop-scoped `fan_id`

### `check_ban_override` (`services/ban_override.py`) — COMPLETE
- Walker-only override: candidate favored by driver/trainer AND offending walker is not → reassign offending walker
- Signature takes `offending_walker` object (not UUID) — needed to pass to `perform_walker_reassignment`
- Also takes `base_weights` and `banned_truck_ids` to pass through to reassignment

### `perform_walker_reassignment` (`services/reassign_walker.py`) — COMPLETE
- Takes walker object (not UUID) — consistent with `check_ban_override`
- Removes walker from `assigned_crews[truck_id]` in place
- Builds `updated_bans = banned_truck_ids + [truck_id]` — prevents reassigned walker from landing back on same truck
- Calls `assign_walkers([walker], ...)` — circular import risk noted, acceptable at this stage

### `assign_drivers` (`services/assign_drivers.py`) — COMPLETE
- Per-truck loop: for each truck pick from remaining driver pool
- Weight per driver: `1` (normal) or `0.05` (consecutive penalty)
- `random.choices` normalizes — 0.05 creates ~1.2% vs ~24.7% chance in 5-driver pool
- Mutates `assigned_crews` in place — dict passed by reference, no return needed

### `assign_trainers` (`services/assign_trainers.py`) — COMPLETE
- Single upfront query for all driver-trainer ban relationships (both directions via `or_()`)
- Two-pass even spread: trucks capped at 2 trainers during first pass via `first_pass_active` flag
- Flag recomputed each iteration — no state leaks between passes
- Calls `calculate_weights` per trainer with combined `banned_truck_ids` (actual bans + capped trucks)

### `assign_walkers` (`services/assign_walkers.py`) — COMPLETE
- Ban query covers all placed crew (drivers + trainers + walkers) in both directions
- Stores `(truck_id, banner_id, is_walker)` tuples — `is_walker` flag determines override eligibility
- `walker_obj_by_id` lookup built upfront to resolve walker objects from IDs for override check
- `is_walker == False` → ban from driver/trainer, stands immediately, skip override check
- One-per-truck even spread via `first_pass_active` flag
- Returns `list` of warnings for all-zero-weight cases

### `assign_trainers` (`services/assign_trainers.py`) — COMPLETE
- All-zero weight detection: resets to flat `[1] * n` and appends warning with `banned_by` list
- Returns `list` of warnings

### `calculate_weights` (`services/calculate_weights.py`) — COMPLETE (post-simulation fixes)
- Fan boosts only apply to eligible (non-banned) trucks — `eligible_trucks = list(set(t for t in fans_by_role[role] if t not in banned_truck_ids))`
- Deduplication via `set()` prevents double boost when multiple fans of same role are on same truck
- Both fixes prevent banned trucks from receiving any weight increase

### `run_dispatch` (`services/run_dispatch.py`) — COMPLETE
- Pool size validation before `assign_drivers`: raises `ValueError` if `len(drivers) < len(trucks)` with message indicating missing slot count
- Fetches active trucks, builds `base_weights` and empty `assigned_crews`
- Calls `assign_drivers` → `assign_trainers` → `assign_walkers` in order
- Collects warnings from `assign_trainers` and `assign_walkers`, merges into single list
- Persists via `TruckAssignment` + `AssignmentMember` — `db.flush()` after each `TruckAssignment` to get ID before creating members
- Returns `(assigned_crews, warnings)` tuple

### `dispatch` router (`routers/dispatch.py`) — COMPLETE
- `POST /dispatch/` endpoint
- Duplicate guard: `409 CONFLICT` if `TruckAssignment` already exists for today
- `ValueError` from service layer converted to `400 BAD REQUEST`
- Response includes `warnings` field — each entry has `employee_id` and `banned_by` list
- Registered in `main.py`

### Deleted
- `check_ban.py` — superseded by bidirectional ban queries built inline in `assign_trainers` and `assign_walkers`

---

## Key Takeaways
- Service layer raises `ValueError`, routers raise `HTTPException` — services must be framework-agnostic
- `or_()` + `.count() == N` is the pattern for verifying mutual existence of multiple rows
- Never use Python `and`/`or` with SQLAlchemy column expressions — always `and_()` and `or_()`
- Reverse lookup dict `{child: parent}` preserves association when flattening nested structures
- `setdefault(key, []).append(val)` — clean one-liner for grouping into a dict of lists
- `random.choices()` normalizes weights automatically — no need to manually redistribute after zeroing banned trucks
- Dicts are passed by reference in Python — mutations inside assignment functions are visible to caller; no return needed
- Per-truck assignment loop (not per-employee) creates better randomness illusion and maps to business mental model
- Store tuples `(truck_id, offending_id)` in ban lookups when you need both pieces later — avoids second lookup
- Single upfront bulk query + dict lookup is always preferred over N queries inside a loop
- `db.flush()` generates the PK without committing — required when child rows need the parent's ID in the same transaction
- Two-pass even spread via `first_pass_active` flag: recompute each iteration, no separate loop, no state leaks

---

## Pending
- Unit tests for dispatch service functions
- Caching layer for `run_dispatch` results (Redis, future)
- Trainer priority ordering (driver-fav trainers first) not yet implemented — currently random order within `available_trainers`
- Manual assignment endpoint for drivers/trainers/walkers not yet implemented
- Circular import (`assign_walkers` → `reassign_walker` → `assign_walkers`) must be resolved before production

## Related ADRs
- ADR-003: Dispatch Service Implementation Decisions
- ADR-004: Dispatch Post-Simulation Bug Fixes
