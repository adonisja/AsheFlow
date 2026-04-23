# ADR-049: Analytics Access Audit and Role-Scoped Fixes

**Date:** 2026-04-23
**Status:** Accepted
**Deciders:** adonisja

---

## Context

As analytics surfaces multiplied across the app (OperationsAnalytics, TrainerDashboard, FieldOps, Dashboard KPI row), role-based access was applied inconsistently. Some panels were visible to roles that have no use for the data; some panels that should exist for self-view were missing entirely; one endpoint had no ownership check allowing any authenticated user to read any employee's profile.

A full audit was conducted covering every analytics card, panel, and endpoint across all roles.

---

## Findings

### Mismatch 1 — Trainer Load panel visible to dispatch (Medium)
**What it shows:** each trainer's count of active trainees.
**Who sees it:** dispatch + management + admin (all visitors to `/operations-analytics`).
**Problem:** dispatch has no authority over trainer assignments. The data is noise and could create confusion.
**Fix:** gate `<TrainerLoadPanel />` behind `management || admin` in `OperationsAnalytics.tsx`.

### Mismatch 2 — Walker/driver self-performance panels missing (High)
**What it shows:** would show each worker their own performance data — grade, presence %, no-shows, inspection pass/fail.
**Who sees it:** nobody; panels didn't exist.
**Problem:** walkers and drivers have performance data stored in the backend but no UI to view it.
**Fix:** added `WalkerSelfPerformancePanel` and `DriverInspectionHistoryPanel` to `FieldOps.tsx`, rendered conditionally by role.

### Mismatch 3 — Fleet Today KPI shows 0/0 (Low, deferred)
**Problem:** ambiguity between "trucks present in yard" and "trucks that departed today". Deferred pending semantic decision.

### Mismatch 4 — Walker profile endpoint has no ownership check (High)
**Endpoint:** `GET /field-ops/walker-profile/{walker_id}`
**Problem:** any authenticated user could pass any walker UUID and read their grade, ratings, and shift history.
**Fix:** replaced `allow_management` dependency with `get_caller_employee`; added check — caller must own the walker_id or have `dispatch/management/admin` role.

### Mismatch 5 — Trainers had no self-view endpoint (High)
**Problem:** `GET /trainer-marks/trainer/{trainer_id}` required the caller to know their own UUID. No `/mine` shortcut existed. Trainers had no way to see their own marks from the UI without knowing their UUID.
**Fix:** added `GET /trainer-marks/mine` and `GET /trainer-marks/mine/summary`; added "My Performance" tab to `TrainerDashboard`.

### Mismatch 6 — Status/Active KPI showed hardcoded string (Low)
**Problem:** the Dashboard KPI row showed a "Status / Active" card that always displayed "Active" regardless of real system state — dead UI.
**Fix:** removed the card and reduced the grid from 3 to 2 columns.

---

## Decision

Fix mismatches 1, 2, 4, 5, 6 immediately. Defer mismatch 3 until the yard-presence vs departure-activity semantic question is resolved.

Role access matrix post-fix:

| Surface | driver | walker | trainee | trainer | dispatch | management | admin |
|---------|--------|--------|---------|---------|----------|------------|-------|
| Dispatch Fill Rate | — | — | — | — | ✓ | ✓ | ✓ |
| Ban Override Freq | — | — | — | — | ✓ | ✓ | ✓ |
| Confirmation Times | — | — | — | — | ✓ | ✓ | ✓ |
| Trainer Load | — | — | — | — | — | ✓ | ✓ |
| My Performance (trainer) | — | — | — | ✓ (own) | — | ✓ | ✓ |
| Walker Profile | — | ✓ (own) | — | — | ✓ | ✓ | ✓ |
| Driver Inspection History | ✓ (own) | — | — | — | ✓ | ✓ | ✓ |

---

## Consequences

- Trainers, walkers, and drivers now have role-appropriate self-view panels.
- Dispatch's analytics view is scoped to dispatch-relevant data only.
- Walker profile endpoint is protected against horizontal privilege escalation.
- Dashboard KPI row no longer shows misleading static data.
- Fleet Today semantic bug remains open — see memory entry.
