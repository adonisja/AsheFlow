# Journal: Dispatch Drag-and-Drop Role Fix
**Date:** 2026-04-16

---

## Context

During a codebase review, `handleDropToTruck` in `DispatchDashboard.tsx` was found to hardcode `role: "walker"` when assigning an employee from the unassigned panel to a truck via drag-and-drop. Any non-walker (trainer, driver, trainee) dragged manually would be stored in the DB with the wrong assignment role.

---

## Fix Applied

**File:** `frontend/src/pages/DispatchDashboard.tsx`

**Problem:** The `ASSIGN` branch of `handleDropToTruck` (line 204–211) sent `role: "walker"` unconditionally for every unassigned-to-truck drop:

```typescript
await axiosClient.post('/dispatch/assign', {
  employee_id: employeeId,
  truck_id: targetTruckId,
  date: selectedDate,
  role: "walker" // default fallback
});
```

**Fix:** Look up the employee's real role from `availablePool` (the already-loaded map of unassigned employees), with a fallback to the broader `employees` map:

```typescript
const emp = availablePool[employeeId] || employees[employeeId];
const role = emp?.role || 'walker';
await axiosClient.post('/dispatch/assign', {
  employee_id: employeeId,
  truck_id: targetTruckId,
  date: selectedDate,
  role,
});
```

No additional API calls required — `availablePool` is populated by `fetchAvailablePool` on every date change and already contains the full employee object for every employee in the unassigned panel.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/DispatchDashboard.tsx` | Replace hardcoded `role: "walker"` with lookup from `availablePool`/`employees` state maps |
