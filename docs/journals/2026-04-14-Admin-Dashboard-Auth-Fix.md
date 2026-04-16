# Journal: Admin Dashboard — Unauthenticated API Calls Fix
**Date:** 2026-04-14

---

## Goal for the Session

Investigate why the admin dashboard was rendering empty — roster blank, KPI counters at zero, workforce breakdown empty, truck fleet empty, no incidents, no training sessions.

---

## Root Cause Analysis

### The symptom

Every data section on `AdminDashboard` was empty despite data existing in the database. The loading spinner resolved normally (no indefinite spin), meaning the requests were completing — just returning nothing.

### The bug

`AdminDashboard.tsx` was importing raw `axios` and making requests directly with a hardcoded base URL:

```typescript
import axios from 'axios';
const API = 'http://localhost:8000/api/v1';

axios.get(`${API}/employees/`)
axios.get(`${API}/trucks/`)
// ...
```

Every other page in the app imports `axiosClient` from `../api/axiosClient`, which attaches the Cognito `idToken` as an `Authorization: Bearer <token>` header via an interceptor. Raw `axios` has no such interceptor — requests go out unauthenticated.

The backend `RoleChecker` dependency on every route returns 401 for unauthenticated requests. `Promise.allSettled` was used to fan out all four fetches — by design it never rejects, it settles all promises regardless. So all four 401 failures were silently absorbed, the state arrays were never populated, and the component rendered with empty data as if the server returned empty lists.

### Why this was hard to notice

- `Promise.allSettled` is the right pattern for fan-out fetches (one failure shouldn't block the others). But it means failed fetches are invisible unless you explicitly check each result's `status` field.
- The loading state resolved correctly (the `finally` block ran), giving no visual signal of failure.
- There were no console errors unless the browser dev tools were open and network tab was being watched.

---

## The Fix

### 1. Replace `axios` with `axiosClient` in `AdminDashboard.tsx`

```typescript
// Before
import axios from 'axios';
const API = 'http://localhost:8000/api/v1';
axios.get(`${API}/employees/`)

// After
import axiosClient from '../api/axiosClient';
axiosClient.get('/employees/?include_inactive=true')
```

All seven API calls (4× GET, 2× PUT, 1× PATCH) updated.

### 2. Add `include_inactive` param to `GET /employees/`

Admin's roster and workforce breakdown need to see inactive employees (the "Inactive Employees" section was always empty because the endpoint only returned `is_active == True`). Added the same `include_inactive: bool = False` query param pattern already used by `GET /trucks/`:

```python
@router.get("/", response_model=list[EmployeeResponse])
def get_all_employees(
    ...
    include_inactive: bool = False,
    ...
):
    q = db.query(Employee)
    if include_inactive:
        if not (caller_groups & {"management", "admin"}):
            raise HTTPException(status_code=403, detail="Access denied.")
    else:
        q = q.filter(Employee.is_active == True)
```

Admin dashboard passes `?include_inactive=true`. All other callers continue to receive active-only.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/AdminDashboard.tsx` | Replaced `axios` + hardcoded URL with `axiosClient`; added `include_inactive=true` to employees and trucks fetches |
| `backend/app/routers/employees.py` | Added `include_inactive: bool = False` query param to `GET /employees/` |
