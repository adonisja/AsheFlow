# ADR-069: Dispatch Router Multi-Tenant Conversion

**Date:** 2026-05-07
**Status:** Implemented

## Context

Phase 1, Step 5 completion. All tables now have `company_id NOT NULL`, but the
dispatch layer was still running unscoped queries — any authenticated user could
see or modify another company's dispatch data.

The root issue was that most dispatch endpoints used `current_user: dict`
(a raw Cognito token payload) which carries no `company_id`. The `company_id`
lives on the `Employee` DB row, not in the JWT.

## Decision

Converted all dispatch router endpoints from `current_user: dict` to
`caller: Employee = Depends(get_caller_employee)`. This gives every handler
direct access to `caller.company_id` for query scoping.

**All queries in `dispatch.py` now filter by `caller.company_id`**, including:
- `TruckAssignment` reads and writes
- `Employee` lookups for alert recipients
- `DispatchConfirmation` history
- `PackageManifest` reads and writes
- Double-dispatch prevention check

**`run_dispatch` service** updated to accept `company_id: UUID` as an explicit
parameter. This is passed from the router, never inferred from DB rows.
`TruckAssignment` and `AssignmentMember` rows are now stamped with the
caller's company_id at creation time.

A `_SEED_COMPANY_ID` fallback remains in `run_dispatch` as a temporary shim for
the test suite, which calls the service directly. This will be removed in the
post-Phase-1 cleanup pass once the test infrastructure is updated to always pass
a company_id.

**`graduate_trainees` service** updated to stamp `Notification` rows with
`trainee.company_id` (the trainee's own company — always correct here since
graduation is per-trainee and trainees belong to exactly one company).

## Pattern established

Service functions that write rows should always accept `company_id` as a
parameter rather than reading it from DB state. This makes the data flow
explicit and prevents accidental cross-company writes if a query returns the
wrong row.

## Test suite

All test fixtures in `conftest.py` and inline model creations in:
- `tests/services/test_run_dispatch.py`
- `tests/services/test_graduate_trainees.py`
- `tests/services/test_analytics.py`

...were updated to pass `SEED_COMPANY_ID = UUID("a0000000-0000-0000-0000-000000000001")`.

97/97 tests passing after the migration.

One stale test (`TestExcessTrainerReSlot::test_excess_trainers_appear_as_walkers_in_crew`)
was updated to reflect the current business rule: excess trainers stay as trainers
distributed across trucks — they are not re-slotted as walkers.

## Files changed

- `backend/app/routers/dispatch.py` — all endpoints converted to `caller: Employee`; all queries scoped by `caller.company_id`; `PackageManifest` creates stamped with `company_id`
- `backend/app/services/run_dispatch.py` — `company_id` parameter added; `TruckAssignment` and `AssignmentMember` stamped; formatted_crews query scoped
- `backend/app/services/graduate_trainees.py` — `Notification` rows stamped with `trainee.company_id`
- `backend/app/models/company.py` — added `ForeignKey("companies.id")` to `CompanyConfig.company_id` and `CompanyZone.company_id` (was plain UUID — SQLAlchemy relationship couldn't infer join)
- `backend/tests/conftest.py` — `SEED_COMPANY_ID` constant added; all helper functions updated
- `backend/tests/services/test_run_dispatch.py` — stale reslot test updated; inline model creations fixed
- `backend/tests/services/test_graduate_trainees.py` — all inline model creations fixed
- `backend/tests/services/test_analytics.py` — all helper functions and inline creations fixed
