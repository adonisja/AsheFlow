# Engineering Journal: April 10, 2026

**Session Start Time**: 2026-04-10
**Session End Time**: 2026-04-10

## Goal for the Session

Implement the remaining discussion.md backlog items:

1. **Schedule Change Requests** on the Preferences page — employees request recurring days off (drop/add/swap), managers approve or deny, status is visible in-place.
2. **Field Operations page** — Check-In with photo capture, Departure with itinerary photo, and Driver → Walker star ratings. All three features needed to be wired to a real backend, not mocked.
3. **Mobile camera compatibility** — evaluate whether the existing `<input capture>` approach works for a future shared-codebase mobile build.

---

## Problems Encountered

### 1. Alembic autogenerate detecting phantom column removals
Every time `alembic revision --autogenerate` was run, it detected that `training_records.trainer_rating` and `training_records.trainee_comments` were "removed" — even though they exist in the database. This caused the generated migrations to include destructive `op.drop_column` statements that would have wiped real training data.

**Why it happened:** The SQLAlchemy `TrainingRecord` model in `training.py` had those columns defined, but an earlier manual migration or `alter_db.py` script had added them directly to Postgres outside of Alembic's awareness, causing a model-vs-DB drift that autogenerate kept trying to "fix" in the wrong direction.

**Fix:** Manually edited each generated migration file before running `upgrade head` to strip the phantom drop_column / add_column lines. Left a note to reconcile the training model columns with a proper stamp migration later.

### 2. Employee ID resolution in FieldOps
The `useAuth()` context exposes `user.username` (Cognito username / Discord ID) and `user.userId` (Cognito `sub`). Neither of these is the PostgreSQL `employees.id` UUID that the backend expects for check-in/departure/rating payloads.

**Why it happened:** The app uses Cognito for auth but stores employees by their Discord ID (`discord_id`) in the DB. There is no direct mapping stored in auth context.

**Fix:** On mount, `FieldOps.tsx` fetches `GET /employees/` and finds the employee whose `discord_id` matches `user.username`. This is the same pattern used in `Schedule.tsx` and `Preferences.tsx`.

### 3. `capture="environment"` locks out photo library on mobile
The initial camera input used `capture="environment"` which forces the rear camera on mobile — but prevents the user from choosing an existing photo from their gallery. On a shared web/mobile codebase this is unnecessarily restrictive.

**Fix:** Removed the `capture` attribute. Mobile browsers present a choice sheet (camera or library); desktop falls back to the normal file picker. This is the correct behavior for both platforms.

---

## Solutions & Procedures

### Backend
- Created `app/models/field_ops.py` with three new SQLAlchemy models: `CheckIn`, `Departure`, `WalkerRating`.
- Created `app/schemas/field_ops.py` with Pydantic create/response schemas for all three.
- Created `app/routers/field_ops.py` with:
  - `GET /field-ops/crew/{employee_id}` — returns today's truck crew for a given employee (excluding themselves), used by the Walker Rating panel to find walkers dynamically.
  - `POST /field-ops/check-in` + `GET /field-ops/check-in/{employee_id}` — create and retrieve check-ins.
  - `POST /field-ops/departure` + `GET /field-ops/departure/{employee_id}` — create and retrieve departures.
  - `POST /field-ops/rating` + `GET /field-ops/rating/walker/{walker_id}` — submit and retrieve walker ratings.
  - All POST endpoints return 400 if a duplicate record exists for the same employee+date (or driver+walker+date for ratings).
- Generated and ran Alembic migration `8523668a4665_add_field_ops_tables` (manually stripped phantom training column drops before running).
- Registered models in `app/models/__init__.py` and router in `app/main.py`.

### Frontend — Preferences (Schedule Change Requests)
- Added `offDays` state and `loadOffDays` / `handleAddOffDay` / `handleDeleteOffDay` handlers.
- Added a new `Section` block with a day-of-week `<select>` that filters out already-requested days.
- Each existing off-day request renders with a status badge (`pending` / `approved` / `rejected`).
- Pending requests show an X button to cancel (DELETE); approved/rejected are read-only.
- Removed a stale empty admin placeholder card that had been left as a comment stub.

### Frontend — FieldOps page
- On mount, resolves the logged-in user's PostgreSQL employee ID from `GET /employees/` using `discord_id === user.username`.
- **CheckInPanel**: fetches today's existing check-in on load to restore state. Converts captured photo to base64 data-URI via `FileReader`, POSTs to `/field-ops/check-in`. Shows photo confirmation after success.
- **DeparturePanel**: same pattern as check-in with `itinerary_photo_url`.
- **WalkerRatingPanel**: fetches `/field-ops/crew/{employee_id}`, filters to `role === 'walker'`, renders a star picker + comment per walker. POSTs to `/field-ops/rating`. Shows "No walkers today" empty state if not dispatched or no walkers on truck.
- Removed all hardcoded mock data (`WALKERS_MOCK`).
- Removed `capture="environment"` from both camera inputs.

---

## Key Takeaways

- **Alembic autogenerate is not a source of truth** — always read the generated migration before running it. If there's model-vs-DB drift from manual SQL scripts, autogenerate will try to "fix" it in the wrong direction. Strip phantom changes before applying.
- **Auth context ≠ DB identity** — Cognito gives you a `sub` and a username; your app's DB has its own UUID primary keys. Always resolve the bridge at the component level (employee lookup) rather than storing it in auth context, which would couple auth to business logic.
- **`capture` attribute is not mobile-safe for all use cases** — on mobile, `capture="environment"` skips the photo library entirely. Removing it gives users the choice and is the correct default for a shared web/native codebase.
- **Shared codebase mobile strategy**: the current architecture (Axios client, base64 photo encoding, REST endpoints) is fully compatible with a React Native / Expo build. Only the camera capture UI component would need to be swapped for `expo-image-picker`; all API logic is reusable as-is.
