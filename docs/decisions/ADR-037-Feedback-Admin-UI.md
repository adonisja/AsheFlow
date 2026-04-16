# ADR-037: Feedback Admin UI — Inbox and Status Management

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The feedback system had a submission surface (`FeedbackModal` + `POST /feedback/`) but no admin-facing review surface. Submitted feedback landed in the database with no way for anyone to triage, act on, or close it from the application.

Additionally, `GET /feedback/` was gated to `management` + `admin`. Feedback is a developer/system concern (bug reports, feature requests) — not an operations concern. Management has no meaningful action to take on a bug report. The read endpoint needed to be tightened to admin-only to match the actual use case.

The `PATCH` status update endpoint did not exist at all.

---

## Decisions

### Backend

**Decision 1: Restrict `GET /feedback/` to admin only.**  
`management` was included in the original guard without a clear rationale. Feedback is a product/engineering signal. Management's operational role (approving PTO, reviewing incidents) has no overlap with triaging bug reports or feature requests.

**Decision 2: Add `PATCH /feedback/{id}/status` (admin only).**  
Three valid status transitions: `new → in_progress → resolved` (and `resolved → new` for reopening). Status validation is done in the handler against a `_VALID_STATUSES` set rather than a Pydantic `Literal` to keep the single source of truth in one place and avoid duplication between schema and handler.

**Decision 3: Add `FeedbackStatusUpdate` schema.**  
Minimal schema — just `status: str`. Validation of the value is the handler's responsibility since it also needs to return a structured error message listing valid options.

### Frontend

**Decision 4: Place the Feedback Inbox inside `AdminDashboard`, not a separate page.**  
The inbox is a triage surface, not a primary work area. It belongs alongside the other admin oversight panels (incidents, training, roster) rather than warranting its own route. Admin can reach it by scrolling the dashboard.

**Decision 5: Filter tabs, not a search box.**  
The four statuses (`all`, `new`, `in_progress`, `resolved`) are the primary triage dimensions. Tab filtering covers the common workflows (review new items, check what's in progress, confirm resolved) without adding query complexity.

**Decision 6: Age badge with color thresholds.**  
Feedback items that have been sitting unactioned for 7+ days get a danger color; 3–6 days get warning. This is the same pattern used in the schedule change request queue and surfaces neglected items without requiring the admin to do date math.

---

## Consequences

**Positive:**
- Submitted feedback is now actionable — admin can triage, mark in-progress, and resolve from the dashboard.
- Management can no longer read feedback; access is now correctly scoped to admin only.
- The `PATCH` endpoint enables full lifecycle management: new → in_progress → resolved → reopen.

**Negative / Trade-offs:**
- Feedback submitters have no visibility into the status of their own submission (no `GET /feedback/my` endpoint). This is acceptable for the current scale — feedback is internal staff, not external customers.
- Employee names are not shown — only `employee_id`. Resolving names would require a join or a second lookup. Acceptable for now; the ID is sufficient to look up the employee in the roster panel above.

---

## Learnings & Growth

A data collection endpoint without a review surface is an incomplete feature. Any time a form submits data that a privileged user needs to act on, the review surface should be built in the same session as the submission surface — not treated as a separate future task.
