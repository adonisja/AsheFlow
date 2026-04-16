# Journal: ScheduleChanges Dead Code Cleanup
**Date:** 2026-04-16

---

## Context

After removing management from `/schedule-changes` (ADR-038), the `isManagement` render branch in `ScheduleChanges.tsx` became unreachable dead code. This journal records the cleanup pass.

---

## Changes Applied

**File:** `frontend/src/pages/ScheduleChanges.tsx`

**Removed:**
- `isManagement` variable (`groups.includes('management')`)
- `isReviewer` variable (`isAdmin || isManagement`)
- `isManagement` from the `useEffect` dependency array
- The `if (isReviewer)` / `if (isAdmin)` split in `useEffect` — simplified to `if (isAdmin)` (admin is the only reviewer role that can reach this page now)
- The entire management render block (lines 324–369 pre-cleanup): pending queue with approve/reject buttons, no analytics, no heatmap

**Kept:**
- `pendingRequests` state and `loadPendingRequests` — still used by the admin render branch
- `allRequests` state and `loadAllRequests` — still used by `ScheduleAnalytics` in the admin branch
- All field staff state and render logic — unchanged

**Result:** The component now has two branches: admin (analytics + pending queue) and field staff (personal form + history). The management dead branch is gone.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/ScheduleChanges.tsx` | Remove `isManagement`, `isReviewer`, management render block; simplify `useEffect` |
