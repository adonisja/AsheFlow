# Journal — Dispatch Hardening, Role Constants, and Secret Hygiene
**Date:** 2026-05-03

## What we did

### Confirmation polling staleness indicator

The `DispatchDashboard` polling loop had an empty `catch` block — three consecutive network failures looked identical to three successful polls returning no changes. Added a `pollFailureCount` ref that increments on each failed tick. After 3 failures `confirmationsStale` flips to `true`, surfacing a dismissible warning banner with a "Retry now" button. The counter and flag reset on any successful response, on date change, and when polling stops (either on completion or navigation away).

### ConfirmDialog wiring for all dispatch actions

Four `window.confirm` / `confirm` calls in `DispatchDashboard.tsx` (Publish, Post Final Crews, Remove from Truck, Clear Dispatch) were replaced with the existing `ConfirmDialog` component. The pattern used here differs slightly from the `useConfirm` hook approach used elsewhere: a single `dialog: DialogConfig | null` state drives one `ConfirmDialog` at the bottom of the tree. Each action calls `openDialog(cfg)` where `cfg` includes the async `onConfirm` callback inline. This keeps the handlers co-located with their actions without needing a hook.

Remove shows the employee's name in the message. Clear uses `variant="danger"` and notes the action cannot be undone.

### Operations Tool relabel

The confirm-all card on AdminDashboard was labelled "Dev Tool" — suggesting it was temporary scaffolding. Renamed to "Operations Tool — Confirm All Pending". The surrounding comment was updated to remove "temporary".

### Role constants

Added to `backend/app/services/constants.py`:
- `FIELD_ROLES`, `MANAGEMENT_ROLES`, `OVERSIGHT_ROLES`, `ASSIGNABLE_ROLES` tuples
- Individual `ROLE_*` string constants for every role

`deps.py` imports `OVERSIGHT_ROLES` for `_PRIVILEGED_ROLES`. `dispatch.py` imports all constants and all ORM-level role comparisons and `role.in_()` calls now use them. Dict comparisons on JSON data (bot responses) were left as literals intentionally — those operate on external data and substituting constants there adds noise without preventing bugs.

### Structured logging

Added `logger = logging.getLogger(__name__)` to `dispatch.py` and `training_injection.py`. Key log points: publish start (INFO, includes publisher username), inject_curriculum call (INFO, truck count), publish complete (INFO, employees notified), reassign helper entry (INFO), no assignment found (WARNING), trainee placed (INFO, truck + trainer), no free slot (WARNING), curriculum entry (INFO, trainee count), record creation per trainee (INFO, phase + IDs).

Python's standard logging is used — no new dependencies.

### UUID crash fix in `record_confirmation`

`UUID(str(employee_id))` was called on raw Redis input without validation. Wrapped in `try/except (ValueError, AttributeError)` at the top of the function. The validated value is stored in `employee_uuid` and all four downstream uses were replaced via `sed`. Bad input now returns HTTP 422 with a descriptive message instead of a 500.

### Bumped trainee notifications

When `_handle_bumped_trainee` found no fallback slot, the event was silently dropped. Now fires `trainee_unassigned` notifications to dispatch/admin (naming the employee and flagging it for manual intervention) and a separate notification to the trainee. The original `pass` was the only thing there — this was an unambiguous data loss bug.

### Null guard in reassign helper

`_reassign_trainee_on_trainer_decline` accessed `new_trainer_emp.name` after a DB lookup that could return `None`. Added fallback to `"Unknown Trainer"` so the notification message never contains a raw `None`. Added a WARNING log when the destination trainer Employee row is missing, and a second guard for the case where `training_record` exists but `new_trainer_id` is falsy.

### Docker-compose secret hardening + `.env.example`

`POSTGRES_PASSWORD`, `SECRET_KEY`, and `INTERNAL_SECRET` changed from `:-weak-fallback` to `:?error message` syntax. Docker Compose hard-fails on startup if any of these are unset. `POSTGRES_USER`, `POSTGRES_DB`, and `REDIS_URL` keep `:-default` fallbacks — they are not security-sensitive.

`.env.example` created at the project root with all required variables, generation instructions for `SECRET_KEY` and `INTERNAL_SECRET` (`python -c "import secrets; print(secrets.token_hex(32))"`), and a header warning against committing `.env`. Confirmed `.env.example` is not gitignored while `.env` is.

---

## What I learned

**`:?` vs `:-` in docker-compose environment values.** Both use shell-style variable expansion. `:-fallback` substitutes the fallback when the variable is unset or empty — silently. `:?message` causes the compose process itself to exit with an error when the variable is unset or empty, printing the message. For secrets this is strictly better: a misconfigured environment fails loudly at startup rather than silently running with a credential that looks correct in logs.

**`pollFailureCount` as a `useRef`, not `useState`.** The failure counter doesn't need to trigger a re-render on every increment — only when it crosses the threshold. Using `useRef` avoids three unnecessary renders per polling interval during normal healthy operation. The stale flag (`confirmationsStale`) is a separate `useState` because it does need to drive a re-render.

**`openDialog(cfg)` vs `useConfirm` hook — when each fits.** The `useConfirm` hook (Promise-based `await confirm(...)`) is clean when confirmation is awaited inline inside an `async` function and the calling component renders its own return tree. The `dialog` state + `onConfirm` callback pattern is cleaner when you have many actions in one component and want to avoid multiple hook declarations. `DispatchDashboard` has four distinct confirm actions and no sub-components — one state object with an `onConfirm` callback is less boilerplate than four `useConfirm` instances.

**Logging publisher identity at the INFO level.** `publish_dispatch` now logs `publisher=current_user.get("username", "unknown")`. In an ops context, knowing who triggered a publish is as important as knowing it happened. The Cognito username is already available in `current_user` — there is no reason not to include it.
