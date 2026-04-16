# ADR-018: Dispatch Service Unit Test Infrastructure

**Date:** 2026-04-11
**Status:** Accepted
**Area:** Testing / Dispatch Services

---

## Context

The dispatch service layer (`calculate_weights`, `assign_drivers`, `assign_trainers`,
`assign_walkers`, `run_dispatch`) had no automated tests. The logic is probabilistic
(weighted random selection), stateful (minimum-count round-robin), and has complex
branching (ban overrides, fallback paths, headcount caps). Manual QA cannot reliably
exercise all paths on every change.

Three bugs were already present in production code before testing began:
1. `perform_walker_reassignment` called `assign_walkers` with the wrong number of arguments
2. The excess-trainer re-slot in `run_dispatch` used dict-syntax on an ORM object
3. The second bug also carried a data corruption risk (mutating `Employee.role` would persist on the next `db.commit()`)

None of these were caught by manual QA because they all require specific conditions
(ban override firing, excess trainer count exceeding threshold) that did not happen
during normal development testing.

---

## Decision

Build a pytest suite against the dispatch service layer using SQLite in-memory databases.
Each test gets a fully isolated, schema-correct database via a shared `db` fixture.

### Key architectural choices

**SQLite in-memory instead of PostgreSQL**
The service code uses SQLAlchemy ORM — it is database-agnostic. SQLite in-memory
databases are instantiated in milliseconds, require no container, and are completely
isolated per test. No test can pollute another.

**Targeted MetaData, not `Base.metadata.create_all`**
Some models (`VehicleInspection`) use PostgreSQL-specific column types (`JSONB`) that
SQLite cannot compile. Calling `Base.metadata.create_all(engine)` would crash immediately.

The solution is a `DISPATCH_TABLES` list containing only the `Table` objects the dispatch
services actually touch. A fresh `MetaData` is built from these via `table.to_metadata(meta)`,
and only those tables are created. This is the canonical approach for testing PostgreSQL apps
with SQLite.

```python
DISPATCH_TABLES = [
    Employee.__table__,
    Truck.__table__,
    TruckAssignment.__table__,
    AssignmentMember.__table__,
    EmployeeRelationship.__table__,
    EmployeeOffDay.__table__,
    TrainerContinuationRequest.__table__,
    TrainingCurriculum.__table__,
    TrainingRecord.__table__,
    TrainingTask.__table__,
    Notification.__table__,
]
```

**Row-builder helpers, not fixtures**
Helper functions (`make_employee`, `make_truck`, `make_assignment`, etc.) are plain
functions, not pytest fixtures. Each test calls only the helpers it needs, keeping
setup minimal and the test's intent legible.

**Patch randomness, don't rely on it**
`assign_drivers`, `assign_walkers`, and `assign_trainers` use `random.choices` for
weighted selection. Any test that asserts a specific truck was chosen must patch
`random.choices` via `unittest.mock.patch`. Tests that rely on a specific random
outcome are not deterministic — they are gambles that pass most of the time.

**Test at the right level**
- Unit tests cover individual services (`assign_trainers`, `assign_walkers`, `calculate_weights`)
- Integration tests cover `run_dispatch` — pipeline wiring, DB persistence, warning thresholds
- Sub-service internals are not re-tested at the integration level

---

## Tests written

| File | Tests | What it covers |
|---|---|---|
| `test_calculate_weights.py` | 10 | Weight zeroing, consecutive penalty, fan boost, bidirectional bonus, base weight immutability |
| `test_assign_drivers.py` | 4 | One driver per truck, no double-assign, shortage handling, consecutive penalty via mock |
| `test_assign_trainers.py` | 9 | Even spread, ban constraints (both directions), fallback warning |
| `test_assign_walkers.py` | 9 | Even spread, hard bans, walker-vs-walker override (all 3 conditions), fallback warning |
| `test_run_dispatch.py` | 9 | Pipeline shape, driver shortage warning, headcount cap, trainer re-slot, DB persistence |
| **Total** | **41** | |

---

## Bugs found during testing

### 1. `perform_walker_reassignment` — wrong argument count
**File:** `app/services/ban_override.py`
**Symptom:** When a walker ban override fired, the evicted walker was silently missing from all trucks.
**Root cause:** `assign_walkers` was called with 5 positional arguments but only accepts 4. `updated_bans` landed in the `db` slot; the real `db` was a spurious fifth argument causing `TypeError`. The exception propagated from inside `check_ban_override` after it returned `True`, so the outer loop continued without placing the evicted walker.
**Fix:** Added `extra_banned_truck_ids: list = None` parameter to `assign_walkers`. Fixed the call in `ban_override.py` to use the keyword argument.

### 2. Excess trainer re-slot — dict syntax on ORM object
**File:** `app/services/run_dispatch.py`
**Symptom:** `TypeError: 'Employee' object does not support item assignment`
**Root cause:** `available_pool["trainers"]` contains `Employee` ORM objects. The re-slot code used `t["role"] = "walker"` (dict syntax), which fails on ORM objects.
**Secondary risk:** Even if corrected to `t.role = "walker"`, this would mark the Employee dirty in the SQLAlchemy session. The `db.commit()` later in `run_dispatch` would permanently demote real trainers to walkers in the database.
**Fix:** Removed the mutation entirely. `assign_walkers` writes `role="walker"` into `assigned_crews` based on the function being called, not the ORM object's role. Excess trainers are appended to the walker pool as Employee objects; they are placed with walker role automatically.

---

## Consequences

- All three production bugs above were found by tests before reaching production.
- The suite runs in ~1 second — no containers, no network, no shared state.
- New dispatch service changes must not reduce the pass count without a corresponding test update documenting why.
- When a new model is imported by a dispatch service, its table must be added to `DISPATCH_TABLES` in `conftest.py`.
- Test failures during development should be logged in `backend/tests/TEST_LOG.md` with the failure reason, approaches tried, and resolution — this builds institutional memory about non-obvious service behavior.
