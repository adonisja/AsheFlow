## Known Bugs and Type Mismatches — AsheFlow Frontend

**Last Updated**: 2026-07-25 (API typing pass, commits 34f0830–ea9290b)

### 1. DispatchView employee_name undefined bug (UNFIXED)

**File**: `frontend/src/components/dashboard/DispatchView.tsx`  
**Impact**: Time-off and off-day request rows always display employee UUID instead of name

**Description**:  
DispatchView renders time-off and off-day pending requests with the pattern:
```tsx
{r.employee_name || r.employee_id}
```

Backend schemas (`TimeOffRequestResponse`, `EmployeeOffDayResponse`) only include:
- `id: UUID`
- `employee_id: UUID`
- `date: date`
- `status: str`

The field `employee_name` is never populated by the backend and defaults to undefined in the frontend, so all requests render the UUID instead of the employee's actual name.

**Root Cause**:  
The backend endpoint `/time-off-requests/` and `/employee-off-days/` return only the foreign-key reference (employee_id), not a denormalized name field. The frontend was scaffolded to display the name but the backend was never wired to include it.

**Workarounds**:
- Join employee table on `employee_id` in backend schemas (adds `employee_name: str | null` field)
- Add a separate lookup of employee names on the frontend after fetch (N+1 query risk)
- Accept UUID display as interim (lowest friction)

---

### 2. Schedule.tsx dead-store: employees setter never read (UNFIXED)

**File**: `frontend/src/pages/Schedule.tsx` (line ~427)  
**Impact**: Low; setter is called but value never read, may indicate missing feature wiring

**Description**:
```tsx
const [employees, setEmployees] = useState<any[]>([]);
// ...
setEmployees(res.data); // called
// employees never referenced in render or callbacks
```

The setter is triggered in a fetch block but the state variable is never used. This pattern suggests incomplete wiring (e.g., a planned feature to display active employees, or a stale API call left behind).

**Decision**: Left untouched to preserve runtime behavior (fetch may have side effects; warming the cache is a valid use case). Flagging as dead-store for future audit.

---

### 3. Remaining `useState<any>` patterns — scope boundaries (OUT OF SCOPE)

As of 2026-07-25, after typing all interface-reuse cases, **187 `any`s remain** globally. These fall into two groups outside the current refactor scope:

#### Group A: Dashboard-summary objects (new DTO design needed)
- ManagementView: `incidentSummary`, `trainingPipeline`, `inspectionFailures`, `checkInSummary`, `handoffSummary`, `walkerStats`, `pendingRTS`
- OperationsAnalytics: all `data` states
- TraineeDashboard: `trainingRecords`

These fetch specialized summary/aggregation endpoints (e.g., `/training/pipeline-summary`, `/field-ops/inspection-failures/summary`) that return compound structures with no single corresponding ORM model or existing interface. Each needs a bespoke DTO interface.

#### Group B: Request-approval queues (missing api/types.ts exports)
- DispatchView: `pendingRequests`, `pendingOffDays`, `pendingChangeRequests`, `fleetAssignments`, `pendingRTS`
- Schedule: `ptoPending`, `offDayPending`, `reworkPending`

Backend schemas exist (`TimeOffRequestResponse`, `EmployeeOffDayResponse`, `AssignmentChangeRequestResponse`, etc.) but are not re-exported in `frontend/src/api/types.ts`. Typing these states requires either:
1. Exporting the schemas from backend and importing in frontend, or
2. Designing new DTOs in TypeScript

Per the approved refactor scope ("keep going on interface-reuse cases"), this work is **pending future design**.

---

### Typing Audit Trail

**Session commits**:
- 34f0830: ManagementView + InspectionSummaryRow interface extension (208→205 `any`s)
- dfb7f75: Incidents + params Record typing (205→197 `any`s)
- b5d2621: AdminDashboard, DispatchHome, Preferences employee/incident imports (197→193 `any`s)
- fd2f841: FieldOps summary states (193→188 `any`s)
- ea9290b: DispatchView urgentIncidents (188→187 `any`s)

**Branches merged**: 91e0b37 (refactor/phase1-cleanup into staging), created clean 208-`any` baseline

**Test coverage**: 695 backend tests green; tsc -b clean; vite build green at every commit
