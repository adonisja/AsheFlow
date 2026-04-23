# ADR-050: Test Infrastructure Expansion — Graduate Trainees and Analytics

**Date:** 2026-04-23
**Status:** Accepted
**Deciders:** adonisja

---

## Context

After Phase 6 work introduced `graduate_trainees.py` and several analytics router functions, the test suite had no coverage for either. Additionally, a latent conftest bug surfaced: `available_pool.py` had been updated to query `time_off_requests` but the test fixture's targeted `DISPATCH_TABLES` list didn't include `TimeOffRequest`, causing all 53 existing tests to fail.

---

## Decisions

### Fix 1: Add TimeOffRequest to DISPATCH_TABLES

`conftest.py` uses a targeted `MetaData` approach (only the tables the dispatch services touch) instead of `Base.metadata.create_all` which would try to compile PostgreSQL JSONB columns in SQLite. When `available_pool.py` was updated to filter by `time_off_requests`, the table was missing from the fixture.

**Fix:** Added `from app.models.time_off_request import TimeOffRequest` and `TimeOffRequest.__table__` to `DISPATCH_TABLES` in `conftest.py`. This is the correct pattern — any time a service query touches a new table, that table must be added to `DISPATCH_TABLES`.

### Decision 2: Patch `_send_graduation_dm` with autouse fixture

`graduate_trainees.py` calls `_send_graduation_dm()` which fires a background thread making HTTP requests to the Discord bot webhook. Running this in tests would:
1. Fail without a live bot
2. Pollute real Discord channels during CI
3. Add non-deterministic timing

**Decision:** Add an `autouse=True` fixture in `test_graduate_trainees.py` that patches `_send_graduation_dm` to a no-op. This is preferred over monkeypatching per-test — all 18 tests in the file need the patch, so `autouse` is cleaner.

### Decision 3: `make_past_assignment` get-or-create pattern

The graduation threshold check counts assignments from the last N days. Tests create past assignments by offset. When two trainees need to share the same past slot (same truck, same date), a naive INSERT fails with `UNIQUE constraint failed: truck_assignments.truck_id, truck_assignments.date`.

**Decision:** Rewrite `make_past_assignment` to query for an existing `TruckAssignment` with that `(truck_id, date)` first, and only INSERT if none exists. This mirrors the real-world scenario where multiple trainees ride the same truck on the same day.

### Decision 4: Separate ANALYTICS_TABLES fixture in test_analytics.py

The analytics router queries `DispatchConfirmation`, which is not in the global `DISPATCH_TABLES` (the dispatch services don't touch it). Rather than add it globally, `test_analytics.py` defines its own `ANALYTICS_TABLES` list and a local `db` fixture that shadows the global one.

**Why not add to global conftest:** Keeping conftest minimal reduces SQLite schema complexity. Tests that don't need `DispatchConfirmation` shouldn't pay to create it.

### Decision 5: `make_confirmation(response_minutes)` helper

Confirmation time analytics computes median and p90 over the difference between `created_at` and `confirmed_at`. To write deterministic tests (e.g., "median of [5, 10, 15] minutes should be 10"), we need exact time deltas.

**Decision:** `make_confirmation` accepts a `response_minutes` parameter. It sets `created_at = datetime.utcnow() - timedelta(minutes=response_minutes)` and `confirmed_at = datetime.utcnow()`. This produces an exact delta for each row, making the arithmetic assertions precise and readable.

---

## Results

| File | Tests | Result |
|------|-------|--------|
| `test_run_dispatch.py` | 12 | 12/12 ✓ |
| `test_available_pool.py` | 41 | 41/41 ✓ |
| `test_graduate_trainees.py` | 18 | 18/18 ✓ (new) |
| `test_analytics.py` | 26 | 26/26 ✓ (new) |
| **Total** | **97** | **97/97 ✓** |

---

## Consequences

- Every new service that queries a table not in `DISPATCH_TABLES` must add it (enforced by test failures, not convention).
- Side-effectful background calls (bot webhooks) must always be patched in tests — prefer `autouse=True` when the entire file needs the patch.
- Analytics tests are isolated in their own fixture rather than polluting the global conftest with analytics-specific tables.
