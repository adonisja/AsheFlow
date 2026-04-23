# Journal: Analytics Access Audit, Fixes, and Test Suite Expansion

**Date:** 2026-04-23
**Phase:** Phase 6 — Analytics, Security, and Testing

---

## What Was Done

### 1. Two-Phase Dispatch Flow (Post Final Crews)

Identified that the backend `POST /dispatch/{date}/finalize` endpoint existed but had no frontend trigger. The dispatch center only exposed "Run Dispatch" and "Publish Initial Confirmations to Discord" (formerly "Publish to Discord"). Added a "Post Final Crews" button that calls the finalize endpoint, completing the two-phase workflow.

Restructured the DispatchDashboard header into three explicit rows:
- Row 1: title + refresh
- Row 2: inputs (trucks, employees, date) + Clear Dispatch
- Row 3: three workflow buttons in a `flex flex-wrap` row (no `sm:flex-row` which caused column split)

### 2. Analytics Access Audit

Performed a full drill-down of every analytics surface across all pages and roles. Identified 6 mismatches between current access and correct access. Documented in `docs/ANALYTICS_ACCESS_AUDIT.md`.

**Mismatches found:**

| # | Issue | Severity |
|---|-------|----------|
| 1 | Trainer Load visible to dispatch (irrelevant data) | Medium |
| 2 | Walker/driver self-performance panels missing (had data, no UI) | High |
| 3 | Fleet Today KPI shows 0/0 (semantic ambiguity bug) | Low |
| 4 | Walker profile endpoint missing ownership check (any role could query any walker) | High |
| 5 | Trainer self-view: no `/mine` endpoint existed, trainers had to know their own UUID | High |
| 6 | Status/Active KPI on Dashboard showed hardcoded "Active" string, not real data | Low |

**Fixes implemented (#1, #2, #4, #5, #6 — #3 deferred):**
- `OperationsAnalytics.tsx`: gated `<TrainerLoadPanel />` behind `management || admin`
- `FieldOps.tsx`: added `WalkerSelfPerformancePanel` (walker role) and `DriverInspectionHistoryPanel` (driver role)
- `field_ops.py`: added `get_caller_employee` dependency + ownership check to `walker-profile/{walker_id}`
- `trainer_marks.py`: added `GET /mine` and `GET /mine/summary` endpoints; added ownership check to `GET /trainer/{trainer_id}`; refactored body into `_marks_for()` helper
- `TrainerDashboard/index.tsx`: added "My Performance" tab backed by `/mine/summary` + `/mine`
- `App.tsx`: removed hardcoded Status/Active KPI card, reduced grid to `sm:grid-cols-2`

### 3. Navbar Analytics Link

Wired the `/operations-analytics` route into the navbar for `management`, `dispatch`, and `admin` groups — both desktop and mobile nav sections.

### 4. Backend `requests` Dependency

`graduate_trainees.py` calls `requests.post()` for the graduation DM webhook but `requests` was not in `requirements.txt`. Added `requests==2.31.0`, rebuilt the Docker image.

### 5. Test Suite Expansion

**Problem: 53 tests failing after `available_pool.py` update**
`available_pool.py` queried `time_off_requests` table but `TimeOffRequest` was missing from `conftest.py`'s `DISPATCH_TABLES`. All 53 existing tests failed with `OperationalError: no such table: time_off_requests`. Fix: added `from app.models.time_off_request import TimeOffRequest` and `TimeOffRequest.__table__` to `DISPATCH_TABLES`.

**New: `test_graduate_trainees.py` (18 tests)**
- `autouse=True` fixture patches `_send_graduation_dm` to silence HTTP calls
- `make_past_assignment()` uses get-or-create pattern to avoid `UNIQUE constraint failed` on `(truck_id, date)` when two trainees share the same past-day slot
- Tests cover: threshold boundary (4 = no grad, 5 = grad), today exclusion, role reset, TrainingRecord/TrainingTask deletion on reset, continuation request nullification, inactive trainee exclusion, empty run

**New: `test_analytics.py` (26 tests)**
- Custom `ANALYTICS_TABLES` fixture includes `DispatchConfirmation` (not in global `DISPATCH_TABLES` because it's analytics-specific)
- Local helpers: `make_open_training_record`, `make_closed_training_record`, `make_override_notification`, `make_confirmation(response_minutes)`
- `make_confirmation` sets `created_at` and `confirmed_at` to produce exact time deltas for median/p90 assertions
- 4 test classes: `TestDispatchFillRate` (6), `TestTrainerLoad` (6), `TestBanOverrideFreq` (6), `TestConfirmationTimes` (8)

**Final suite: 97/97 passing.**

---

## Key Decisions

- **Separate ANALYTICS_TABLES fixture** rather than adding `DispatchConfirmation` to the global conftest, since not all tests need it and it keeps the global fixture minimal.
- **`make_past_assignment` get-or-create pattern** so multiple trainees can share the same `(truck, date)` slot without hitting the unique constraint.
- **`_send_graduation_dm` autouse patch** prevents background threads making real HTTP calls during test runs — essential for CI.
- **Fleet Today #3 deferred** — semantic decision needed (yard-presence count vs departure-activity count). Tracked separately.

---

## Files Changed

**Backend:**
- `app/routers/field_ops.py` — ownership check on walker-profile
- `app/routers/trainer_marks.py` — `/mine`, `/mine/summary`, ownership check, `_marks_for` helper
- `requirements.txt` — added `requests==2.31.0`
- `tests/conftest.py` — added `TimeOffRequest` to `DISPATCH_TABLES`
- `tests/services/test_graduate_trainees.py` — new, 18 tests
- `tests/services/test_analytics.py` — new, 26 tests

**Frontend:**
- `src/components/layout/Navbar.tsx` — analytics nav link for mgmt/dispatch/admin
- `src/pages/DispatchDashboard.tsx` — Post Final Crews button, three-row layout
- `src/pages/OperationsAnalytics.tsx` — gate TrainerLoadPanel behind mgmt/admin
- `src/pages/FieldOps.tsx` — WalkerSelfPerformancePanel, DriverInspectionHistoryPanel
- `src/pages/TrainerDashboard/index.tsx` — My Performance tab
- `src/App.tsx` — removed Status/Active KPI card

**Docs:**
- `docs/ANALYTICS_ACCESS_AUDIT.md` — new audit report
- `docs/decisions/ADR-049-Analytics-Access-Audit-And-Fixes.md` — new
