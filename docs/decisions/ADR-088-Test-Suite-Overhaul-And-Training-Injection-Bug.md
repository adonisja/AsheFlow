# ADR-088: Test Suite Overhaul and Training Injection Bug Fix

**Date:** 2026-05-16
**Status:** Accepted

## Context

The test suite had been failing intermittently and was not comprehensive enough to catch real production bugs. Two specific gaps were identified:

1. `test_available_pool.py` did not exist — the `get_available_pool` and `get_unavailable_staff` services had zero test coverage.
2. `test_training_injection.py` did not exist — the `inject_curriculum` service had zero test coverage.

Writing tests for `inject_curriculum` immediately surfaced a production bug: the service never set `company_id` on any `TrainingRecord` or `TrainingTask` row it created. On PostgreSQL (which enforces NOT NULL), this would have crashed every dispatch that included trainees, silently at the database layer.

## Root Cause of the Bug

`inject_curriculum` was written before the multi-tenant migration (ADR-063/064) added `company_id` as a NOT NULL column to `training_records` and `training_tasks`. The service was never updated to pass `company_id` through to the rows it inserts. SQLite (used in tests at the time) did not catch this because the original test suite did not cover this service at all.

## Decision

### conftest.py fixes
- Added `ShiftSession` to the `DISPATCH_TABLES` list so shift session tests can run.
- Fixed `make_off_day` and `make_time_off_request` helpers: both were missing `company_id=employee.company_id`, causing `IntegrityError` on every call.
- Added four new row-builder helpers: `make_time_off_request`, `make_curriculum`, `make_training_record`, `make_shift_session`.

### test_available_pool.py (25 tests)
Full coverage of `get_available_pool` and `get_unavailable_staff`:
- Active field staff appear in pool by role; inactive excluded
- Management/admin roles never appear
- Approved recurring off-day on target weekday excludes; pending/wrong-day do not
- Approved PTO on target date excludes; pending/wrong-date do not
- Multi-tenant isolation: other-company employees never returned
- `company_id=None` raises `ValueError`
- `get_unavailable_staff` returns correct `reason` field, respects `roles` filter, excludes trainees

### test_training_injection.py (28 tests)
Full coverage of `inject_curriculum`:
- No trainees → no records (early return)
- Phase advancement: first day→phase 1; closed→advance; not closed→same; phase 4 closed→skip
- Curriculum task injection: correct tasks per phase; phase 4 generates demonstration tasks from mandatory phase 1–3 items only; non-mandatory items included in phases 1–3
- Debt rollover: uncompleted mandatory tasks roll over; age incremented; escalated at threshold; completed tasks do not roll; deduplication by topic_title across records
- Continuation requests: swap when available; keep original when absent; nullified after resolution; pending nullified
- Past record locking
- Idempotency: existing today record updates trainer, no duplicate
- Persistence: records committed; multiple trainees each get their own record

### inject_curriculum bug fix
- Added `company_id: Optional[UUID] = None` parameter to function signature
- Passed `company_id=company_id` to all four model instantiations: `TrainingRecord`, and the three `TrainingTask` constructors (debt task, demonstration task, coverage task)
- Updated the router call in `dispatch.py` to pass `company_id=caller.company_id`

## Consequences

- 154 tests total, all passing
- The `company_id` bug would have caused a `500 Internal Server Error` on every dispatch with trainees in production — it is now fixed before any trainee was ever dispatched on the live system
- The test suite now catches multi-tenant isolation regressions at the service layer
