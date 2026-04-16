# Journal: Security Audit — Section 4 Feature Gaps and Polish
**Date:** 2026-04-15

---

## Context

Section 4 addressed the final category from the full codebase audit: feature gaps, input validation holes, and UI polish items. None of these were security vulnerabilities in the traditional sense, but they represented reliability risks (unbounded DB writes, stale data with no recourse) and a significant UX gap (the notification system existed end-to-end in the backend but had zero frontend presence in the global nav).

Four items were implemented.

---

## Fixes Applied

---

### 4.1 — Notification Bell Added to Navbar

**Files:** `frontend/src/components/layout/Navbar.tsx`

**Problem:** The backend has a complete notification system — `GET /notifications/{employee_id}`, `PATCH /notifications/{id}/read`, `PATCH /notifications/employee/{id}/read-all` — but the Navbar had no bell icon, no unread badge, and no polling. Notifications were only visible on the Schedule and Preferences pages via the page-level `NotificationBanner` component. Any notification type sent to a user browsing any other page would go completely unseen.

**Implementation:**

A `useNotifications` hook was added inline in the Navbar module. On mount (when authenticated), it calls `GET /employees/me` to resolve the employee DB UUID, then immediately fetches unread notifications and sets a 30-second polling interval. The interval is cleared on unmount.

A `NotificationDropdown` component renders as an absolutely-positioned panel below the bell button. It handles click-outside dismissal via a `mousedown` document listener. Individual notifications can be dismissed (marked read), or all can be cleared at once via "Mark all read".

The bell button shows a red badge with the unread count (capped at `9+` display). It sits between the username and the sign-out button in the desktop nav.

**Key decisions:**
- 30s polling was chosen over WebSockets — polling is simpler, stateless, and sufficient for operational notifications (approval results, incident alerts). WebSockets are appropriate if real-time push is ever required.
- `GET /employees/me` is called once per session rather than reading from AuthContext — the AuthContext does not store the employee DB ID, and adding it there would widen the context scope beyond auth concerns.
- Polling errors are silently swallowed — a transient network failure should not surface an error to the user when checking for notifications.

---

### 4.2 — NotificationBanner Extended to All Notification Types

**File:** `frontend/src/components/NotificationBanner.tsx`

**Problem:** The `Notification` type was a hard-coded union of four values: `'pto_approved' | 'pto_rejected' | 'offday_approved' | 'offday_rejected'`. The backend sends many other types: `schedule_change_approved`, `schedule_change_rejected`, `incident_info`, `incident_warning`, `incident_critical`, `incident_resolved`, and more. Any notification with an unlisted type fell through to a `?? typeStyle.pto_approved` fallback — rendering incident alerts with a green checkmark, for instance.

**Fix:** Replaced the `Record<string, style>` lookup with a `styleForType(type: string)` function that determines style by suffix/substring pattern:
- `_approved` suffix → green success style
- `_rejected` suffix → red danger style
- `critical` or `warning` in type → amber warning style
- All others → blue info style

The `Notification.type` field was widened from the union to `string`. The component now handles any current or future notification type correctly without requiring a code change when new types are added.

---

### 4.3 — Input Length Caps on All Unbounded String Fields

**Files:** `backend/app/schemas/incident.py`, `backend/app/schemas/field_ops.py`, `backend/app/schemas/training.py`, `backend/app/schemas/feedback.py`, `backend/app/schemas/assignment_change_request.py`, `backend/app/routers/schedule_change_requests.py`

**Problem:** Free-text string fields across multiple schemas had no `max_length` constraint. An authenticated user could submit an arbitrarily large payload, writing unbounded data directly to Postgres `Text` columns. This is a denial-of-service risk at the DB storage layer — not an injection vulnerability, but a resource exhaustion one.

**Fields capped:**

| Schema | Field | Cap |
|---|---|---|
| `incident.py` | `description` | 2 000 chars |
| `incident.py` | `incident_location` | 300 chars |
| `incident.py` | `witness_name`, `body_part_affected` | 200 chars |
| `field_ops.py` | `WalkerRatingCreate.comment` | 500 chars |
| `field_ops.py` | `FuelMileageLogCreate.notes`, `FuelMileageLogPatch.notes` | 500 chars |
| `field_ops.py` | `VehicleInspectionCreate.notes` | 500 chars |
| `training.py` | `topic_title` | 200 chars |
| `training.py` | `TrainingTaskBase.description` | 1 000 chars |
| `training.py` | `trainer_comments`, `manager_comments`, `trainee_comments` | 2 000 chars |
| `training.py` | `TrainerCommentCreate.comments`, `ManagerCommentCreate.comments`, `TraineeReviewCreate.trainee_comments` | 2 000 chars |
| `feedback.py` | `message` | 2 000 chars |
| `assignment_change_request.py` | `reason` | 500 chars |
| `schedule_change_requests.py` | `reason` | 500 chars |

All caps are enforced at the Pydantic schema layer — they run before the database is touched and return structured 422 responses. No DB migrations needed since the underlying columns remain `Text`.

**Cap rationale:** 2 000 chars for narrative fields (incident descriptions, training comments) is generous for real operational use. 500 chars for reason/note fields is sufficient for operational context. Tighter caps (200–300) on structured fields like location and name prevent padding attacks without affecting legitimate use.

---

### 4.4 — Refresh Buttons on ManagementView and DispatchDashboard

**Files:** `frontend/src/components/dashboard/ManagementView.tsx`, `frontend/src/pages/DispatchDashboard.tsx`

**Problem:** Both views loaded data once on mount with no way for the user to force a refresh without navigating away and back. In an operational context where dispatches are running and incidents are being filed throughout the day, stale dashboard data has real consequences — a manager could be looking at out-of-date incident counts or fleet return status.

**ManagementView fix:**
- Extracted all seven `axiosClient.get(...)` calls into a `loadAll` function wrapped in `useCallback`.
- Changed to `Promise.allSettled` so a single failing endpoint doesn't block the rest.
- Added `isRefreshing` state that drives a spinning `RefreshCw` icon in the header.
- The refresh button is disabled while a refresh is in flight to prevent concurrent duplicate requests.

**DispatchDashboard fix:**
- Added `RefreshCw` to the icon imports.
- Added a refresh button next to the page title that re-calls `fetchDispatchData()`, `fetchAvailablePool()`, and `fetchUnavailableStaff()` — the same three fetches that run when `selectedDate` changes.
- The button inherits the existing `isLoading` state for the spinner/disabled state, keeping the implementation consistent with how dispatch loading already works.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/components/layout/Navbar.tsx` | Added `useNotifications` hook, `NotificationDropdown` component, `notifIcon` helper; bell button with unread badge wired into desktop nav |
| `frontend/src/components/NotificationBanner.tsx` | Replaced hard-coded type union and style map with `styleForType()` pattern-matching function; widened `type` to `string` |
| `backend/app/schemas/incident.py` | `max_length` on `description`, `incident_location`, `witness_name`, `body_part_affected` |
| `backend/app/schemas/field_ops.py` | `max_length` on `comment`, `notes` (fuel log create/patch, inspection) |
| `backend/app/schemas/training.py` | `max_length` on `topic_title`, `description`, all comment fields |
| `backend/app/schemas/feedback.py` | `max_length=2000` on `message` |
| `backend/app/schemas/assignment_change_request.py` | `max_length=500` on `reason` |
| `backend/app/routers/schedule_change_requests.py` | `max_length=500` on inline `reason` field; added `Field` import |
| `frontend/src/components/dashboard/ManagementView.tsx` | `loadAll` callback, `Promise.allSettled`, `isRefreshing` state, refresh button in header |
| `frontend/src/pages/DispatchDashboard.tsx` | Refresh button wired to dispatch/pool/unavailable fetches; `RefreshCw` import |
