# ADR-059: Dispatch Hardening, Role Constants, and UI Confirmation Gates

**Status:** Accepted  
**Date:** 2026-05-03  
**Author:** adonisja

---

## Context

A codebase audit after Phase 7 revealed several classes of issues across the frontend and backend that needed addressing before the system could be considered stable for regular use:

1. **Silent data loss** — when a trainee was bumped from their assignment because no fallback trainer slot existed, the event was silently dropped. Dispatch had no visibility.

2. **UUID crash path** — `record_confirmation` called `UUID(str(employee_id))` on potentially malformed input from Redis without validation. A bad value raised an unhandled `ValueError` that surfaced as a 500 rather than a 422.

3. **Silent polling failures** — the confirmation polling loop in `DispatchDashboard` had an empty `catch` block. Three consecutive network failures looked identical to three successful polls returning no changes. Dispatch had no way to know the displayed state might be stale.

4. **`window.confirm` throughout dispatch UI** — four destructive or high-impact actions (Publish, Post Final Crews, Remove from Truck, Clear Dispatch) used `window.confirm`, which is browser-native, unstyled, and blocked by some browser policies. The project already had a `ConfirmDialog` component that went unused in these flows.

5. **"Dev Tool" label** — the confirm-all operations card on AdminDashboard was labelled "Dev Tool", implying it was temporary scaffolding. It is a legitimate dispatch operations tool.

6. **Role strings scattered as literals** — 23 backend files contained bare `"driver"`, `"trainer"`, `"admin"` etc. string literals with no single source of truth. A typo or future role rename would require a full-codebase grep.

7. **No structured logging** — the three most critical flows (dispatch publish, curriculum injection, trainer decline reassignment) had no log output. Debugging production issues required reading the DB directly.

8. **Weak secrets in docker-compose** — `SECRET_KEY`, `INTERNAL_SECRET`, and `POSTGRES_PASSWORD` had inline `:-fallback` defaults that would silently start a container with dev-grade credentials if `.env` was missing. No `.env.example` existed to guide setup.

9. **Null crash in reassign helper** — `_reassign_trainee_on_trainer_decline` accessed `new_trainer_emp.name` without guarding for the case where the destination trainer's `Employee` row could not be found.

---

## Decisions

### 1. Bumped trainee notifications

When `_handle_bumped_trainee` finds no fallback slot, it now creates:
- A `trainee_unassigned` in-app notification to all dispatch/admin employees naming the bumped trainee and marking it as requiring manual intervention.
- A `trainee_unassigned` notification to the trainee themselves.

The `pass` fallback was replaced in `backend/app/routers/dispatch.py`.

### 2. UUID input validation in `record_confirmation`

Added an explicit `try/except (ValueError, AttributeError)` guard around `UUID(str(employee_id))` at the top of `record_confirmation`. The validated result is stored in `employee_uuid` and all four downstream `UUID(str(employee_id))` call sites were replaced with it via `sed`. The endpoint now returns HTTP 422 with a descriptive message on bad input instead of a 500.

### 3. Confirmation polling staleness indicator

`DispatchDashboard` now tracks `pollFailureCount` (a `useRef`) across interval ticks. After 3 consecutive failures, `confirmationsStale` is set to `true` and a dismissible warning banner appears:

> "Confirmation data may be stale — the server hasn't responded to the last 3 polls. Check your connection or refresh manually."

The banner includes a "Retry now" button that calls `fetchConfirmations()` directly and resets the stale flag. The failure counter and stale flag are cleared on any successful response, on date change, and when polling stops.

### 4. ConfirmDialog for all destructive dispatch actions

All four `window.confirm` / `confirm` calls in `DispatchDashboard.tsx` were replaced with the existing `ConfirmDialog` component. A single `dialog` state object (typed `DialogConfig | null`) drives one `ConfirmDialog` instance at the bottom of the component tree. `openDialog(cfg)` sets it; `closeDialog()` clears it. Each caller is now a synchronous function that calls `openDialog` and passes its async logic as the `onConfirm` callback.

- **Publish** → `variant="default"`, label "Publish"
- **Post Final Crews** → `variant="default"`, label "Post Final Crews"
- **Remove from Truck** → `variant="danger"`, label "Remove", message includes the employee's name
- **Clear Dispatch** → `variant="danger"`, label "Clear Dispatch", message notes it cannot be undone

### 5. Operations Tool label

"Confirm All Pending (Dev Tool)" renamed to "Operations Tool — Confirm All Pending". The surrounding code comment was also updated from "temporary" to reflect its actual role as an operational batch tool.

### 6. Role constants

`backend/app/services/constants.py` now exports:

```python
FIELD_ROLES: tuple[str, ...]    = ("driver", "trainer", "trainee", "walker")
MANAGEMENT_ROLES: tuple[str, ...]  = ("management", "admin")
OVERSIGHT_ROLES: tuple[str, ...]   = ("management", "admin", "dispatch")
ASSIGNABLE_ROLES: tuple[str, ...]  = ("driver", "trainer", "trainee", "walker")

ROLE_DRIVER    = "driver"
ROLE_TRAINER   = "trainer"
ROLE_TRAINEE   = "trainee"
ROLE_WALKER    = "walker"
ROLE_DISPATCH  = "dispatch"
ROLE_MANAGEMENT = "management"
ROLE_ADMIN     = "admin"
```

`backend/app/api/deps.py` imports `OVERSIGHT_ROLES` and uses it for `_PRIVILEGED_ROLES`. `backend/app/routers/dispatch.py` imports all constants and replaces all ORM-level `.role == "..."` comparisons and `role.in_([...])` calls. The `RoleChecker` instantiation and the inline `privileged` set in `record_confirmation` both use constants.

Dict-level comparisons against JSON data returned from the bot (`m["role"] == "trainer"`) are intentionally left as literals — those operate on external data, not ORM role fields.

### 7. Structured logging

A module-level `logger = logging.getLogger(__name__)` was added to:
- `backend/app/routers/dispatch.py`
- `backend/app/services/training_injection.py`

Log points:

| Location | Level | Message |
|---|---|---|
| `publish_dispatch` start | INFO | `date=, publisher=` |
| `inject_curriculum` call site | INFO | `date=, truck_count=` |
| `publish_dispatch` complete | INFO | `date=, employees_notified=` |
| `_reassign_trainee_on_trainer_decline` start | INFO | `trainer_id=, date=` |
| No assignment found | WARNING | `trainer_id=, date=` |
| Trainee placed | INFO | `trainee, truck, trainer, date` |
| No free slot | WARNING | `trainee, date` |
| `inject_curriculum` entry | INFO | `date=, trainees=` |
| `inject_curriculum` no trainees | DEBUG | `date=` |
| Record creation per trainee | INFO | `phase=, trainee=, trainer=, date=` |

### 8. Docker-compose secret hardening

Weak `:-fallback` defaults for `POSTGRES_PASSWORD`, `SECRET_KEY`, and `INTERNAL_SECRET` replaced with `:?error message` syntax. Docker Compose hard-fails at startup if any required variable is unset, rather than silently starting with dev-grade credentials.

`.env.example` created at the project root with all required variables documented, generation instructions for secrets, and a header warning against committing `.env`.

`POSTGRES_USER`, `POSTGRES_DB`, and `REDIS_URL` retain `:-default` fallbacks since they are not security-sensitive.

### 9. Null guard in `_reassign_trainee_on_trainer_decline`

`new_trainer_name` now falls back to `"Unknown Trainer"` when `new_trainer_emp` is `None` (DB row missing for the destination trainer). Added a `WARNING` log at that branch. A secondary guard was added for `training_record and not new_trainer_id` to log when the record cannot be updated rather than silently skipping it.

---

## Alternatives Rejected

- **Throw on polling failure instead of showing stale banner** — would interrupt the dispatch workflow for transient network issues. The stale banner is non-blocking and dismissible.
- **Replace all role literals across all 23 router files** — high churn for low immediate risk. Applied constants only to the files where they matter most (`dispatch.py`, `deps.py`). Other files can migrate incrementally.
- **docker secrets / vault** — over-engineered for the current deployment. `:?` hard-failure is sufficient to prevent accidental weak-credential starts.

---

## Files Changed

**Backend**
- `backend/app/services/constants.py` — added role constants
- `backend/app/api/deps.py` — `_PRIVILEGED_ROLES` uses `OVERSIGHT_ROLES`
- `backend/app/routers/dispatch.py` — UUID guard, role constants, bumped-trainee notifications, logging, null guard
- `backend/app/services/training_injection.py` — logger added, log points at entry and record creation

**Frontend**
- `frontend/src/pages/DispatchDashboard.tsx` — staleness indicator, ConfirmDialog wiring, `window.confirm` removal
- `frontend/src/pages/AdminDashboard.tsx` — Operations Tool label

**Infrastructure**
- `docker-compose.yml` — `:?` required-var enforcement for secrets
- `.env.example` — new file, documents all required variables
