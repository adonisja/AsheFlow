# ADR-036: Fix — Drag-and-Drop Assignment Hardcoded `"walker"` Role

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

`handleDropToTruck` in `DispatchDashboard.tsx` handles two drop scenarios:

1. **Truck-to-truck** (`sourceTruckId` present) — calls `PATCH /dispatch/assign` to move an existing member; no role is sent.
2. **Unassigned-to-truck** (`sourceTruckId` absent) — calls `POST /dispatch/assign` with the employee's `role`.

In the second case, `role` was hardcoded as `"walker"`. Any employee dragged from the unassigned panel — regardless of their actual role — was registered as a walker in the assignment record. A trainer dragged manually would appear in the crew grid with the correct display role (sourced from `employees[id].role`) but be stored in the DB with `role = "walker"`, creating a mismatch between the assignment record and the employee's real function on the truck.

The `availablePool` state already contains the full employee object (including `role`) for every employee in the unassigned panel. The data was present; it simply wasn't used.

---

## Considered Options

**Option 1: Look up role from `availablePool`, fall back to `employees` map**  
`const emp = availablePool[employeeId] || employees[employeeId]; const role = emp?.role || 'walker';`  
Uses already-loaded state, no extra API call.

**Option 2: Add `role` as drag-transfer data**  
Store the role string in `dataTransfer` alongside `employeeId` in `handleDragStart`, read it back in `handleDropToTruck`.

**Option 3: Derive role server-side from the employee record**  
Send only `employee_id` and let the backend resolve the role from the DB.

---

## Trade-offs

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Extra API call | None | None | None |
| State already available | ✅ yes | ✅ yes | N/A |
| Requires backend change | No | No | Yes |
| Risk of stale data | Minimal — pool refreshed on date change | Same | None |
| Code complexity | Lowest | Slightly more surface area | Requires backend refactor of endpoint contract |

---

## Decision

Option 1. `availablePool` is populated by `fetchAvailablePool` and always contains the full employee record for every unassigned employee visible in the panel. Reading from it is the minimal, zero-cost fix. `employees` is a secondary fallback for the unlikely case that `availablePool` hasn't hydrated yet. The `|| 'walker'` final fallback preserves the original behavior only if neither map has the employee.

---

## Consequences

**Positive:**
- Trainers, trainees, and drivers dragged from the unassigned panel are now stored with their correct role in the assignment record.
- The displayed role in the crew grid (from `employees[id].role`) and the stored role in the DB are now consistent.

**Negative / Trade-offs:**
- None. The `|| 'walker'` fallback is still present for defensive completeness but should never fire in normal operation.

---

## Learnings & Growth

When a component renders data from a state map, that map is the correct source for derived values in event handlers — not a hardcoded fallback. Any time a handler sends a value to an API that could instead be read from already-loaded state, it should be.
