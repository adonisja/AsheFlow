# Journal: Persistent Dispatch Confirmations and Audit Log
**Date:** 2026-04-18

---

## Context

Two P1/P3 items from the discussion backlog were addressed: making dispatch confirmations persistent (previously Redis-only with 48h TTL), and adding an audit log to track who approved what actions across the system.

---

## Changes Applied

### `DispatchConfirmation` model and migration

New table: `dispatch_confirmations`. Fields: `employee_id`, `date`, `status`, `confirmed_at`, `source`, `created_at`. Unique constraint on `(employee_id, date)` — one record per person per day.

Two write points:
1. **`POST /dispatch/{date}/publish`** — after seeding Redis, iterates all assigned employee IDs and inserts `pending` rows for any that don't already exist (idempotent re-publish).
2. **`POST /dispatch/{date}/confirmations`** — after writing to Redis, upserts the DB row with the new status and `confirmed_at` timestamp.

New analytics endpoint: `GET /dispatch/confirmations/history?start_date=&end_date=` — returns all confirmation records in the date range, ordered by date and employee. Accessible to dispatch and admin.

Migration: `d3f2a1b4c5e6_add_dispatch_confirmations_table.py`. Applied clean.

### `AuditLog` model and migration

New table: `audit_logs`. Fields: `actor_id` (FK → employees, SET NULL on delete), `action_type`, `target_table`, `target_id`, `before_snapshot` (JSONB), `after_snapshot` (JSONB), `created_at`. Immutable — insert only.

Migration: `e1a2b3c4d5f6_add_audit_logs_table.py`. Applied clean.

### `write_audit()` helper (`backend/app/services/audit.py`)

Single function. Appends an `AuditLog` row to the SQLAlchemy session without committing. Caller commits. This keeps the audit row in the same transaction as the state change it records — atomic by design.

Actor resolution: accepts `actor_id` as a string (Cognito sub). Attempts UUID parse; skips silently if it fails. This means audit rows are still written even when the actor cannot be resolved to an employee UUID.

### Endpoints wired

| Router file | Endpoints | Action types |
|---|---|---|
| `time_off_requests.py` | `/approve`, `/reject` | `pto.approved`, `pto.rejected` |
| `schedule_change_requests.py` | `/approve`, `/reject` | `schedule_change.approved`, `schedule_change.rejected` |
| `assignment_change_requests.py` | `/approve`, `/reject` | `assignment_change.approved`, `assignment_change.rejected` |
| `incidents.py` | `/resolve` | `incident.resolved` |

Each endpoint changed `_: dict = Depends(...)` to `current_user: dict = Depends(...)` where the actor dict was previously discarded, in order to pass `current_user.get("id")` to `write_audit`.

### `GET /audit/` endpoint

New router: `backend/app/routers/audit.py`. Registered in `main.py`. Accepts filters: `action_type` (prefix `LIKE`), `actor_id`, `target_table`, `start_date`, `end_date`. Joins `employees` to return `actor_name`. Management and admin only.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/models/dispatch_confirmation.py` | New |
| `backend/app/models/audit_log.py` | New |
| `backend/app/services/audit.py` | New |
| `backend/app/routers/audit.py` | New |
| `backend/app/models/__init__.py` | Registered both new models |
| `backend/app/main.py` | Registered audit router |
| `backend/app/routers/dispatch.py` | DB seeding on publish, upsert on confirmation, history endpoint |
| `backend/app/routers/time_off_requests.py` | `write_audit` on approve/reject |
| `backend/app/routers/schedule_change_requests.py` | `write_audit` on approve/reject |
| `backend/app/routers/assignment_change_requests.py` | `write_audit` on approve/reject |
| `backend/app/routers/incidents.py` | `write_audit` on resolve |
| `backend/alembic/versions/d3f2a1b4c5e6_...` | New migration |
| `backend/alembic/versions/e1a2b3c4d5f6_...` | New migration |
