# Journal: Assignment Change Requests
**Date:** 2026-04-10

## Context

Walkers and trainers occasionally need to be on a different truck than dispatch assigned them — shift swaps, logistical conflicts, or personal reasons. Previously this had no formal channel: the worker would contact dispatch verbally and hope for a manual override. The change request system formalizes this into a trackable, auditable workflow.

## What Was Built

### Backend

**Model** (`backend/app/models/assignment_change_request.py`):
- `id`, `employee_id` (FK CASCADE), `requested_date` (Date), `reason` (Text, nullable)
- `status`: `pending | approved | rejected`
- `reviewed_by` (FK SET NULL — records who acted on it without blocking deletes)
- `created_at`, `resolved_at`

**Router** (`backend/app/routers/assignment_change_requests.py`):
| Endpoint | Access | Purpose |
|---|---|---|
| `POST /` | walker / trainer / admin | Submit request; one pending per employee per date; notifies all active dispatch/management/admin |
| `GET /pending` | dispatch / management / admin | List all pending, sorted by date ascending (most urgent first) |
| `GET /employee/{id}` | walker / trainer / admin | Own request history |
| `PATCH /{id}/approve` | dispatch / management / admin | Approve; notifies employee |
| `PATCH /{id}/reject` | dispatch / management / admin | Reject; notifies employee |
| `DELETE /{id}` | walker / trainer / admin | Self-cancel a pending request (ownership enforced; admin bypasses) |

**Alembic migration:** `b3cfc071a7ff` — creates `assignment_change_requests` table with indexes on `employee_id` and `requested_date`. Phantom `training_records.trainer_rating` and `training_records.trainee_comments` drop lines stripped before applying (recurring drift issue).

### Frontend

**Preferences.tsx** — "Truck Reassignment Requests" section:
- Visible only to walkers and trainers (role-gated via `groups`)
- Date picker (min = today) + optional reason text input
- Submit button calls `POST /assignment-change-requests/`
- List of own requests with status badges (pending / approved / rejected)
- X button on pending items calls `DELETE /assignment-change-requests/{id}` for self-cancel

**App.tsx Dashboard — Pending Approvals card** (dispatch/management/admin view):
- Now fetches three sources: time-off requests, off-day requests, and assignment change requests
- All three rendered as inline cards with approve/reject icon buttons
- Reassignment requests show employee name, date, and optional reason
- Empty state unchanged; scrollable list when multiple pending items exist

## Design Decisions

- **One pending per employee per date** — prevents duplicate noise in the dispatch queue. A 409 is returned if a pending request already exists for that combination.
- **Notification on submit** — all active dispatch/management/admin employees are notified immediately so requests don't get lost.
- **Actual truck swap is manual** — approval marks the request resolved and notifies the employee, but the dispatcher must still perform the swap via the drag-and-drop board or PATCH `/dispatch/assign`. This keeps the approval step lightweight and doesn't auto-mutate existing assignments.
- **reviewed_by FK** — resolves the reviewer's Employee record via their discord_id from the JWT. Nullable so approvals don't fail if the reviewer has no employee record.
- **Self-cancel via DELETE** — cleaner than adding a `status=cancelled` variant. Removes the row entirely; no lingering cancelled clutter in the history list.
