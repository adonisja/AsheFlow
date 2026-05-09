# Engineering Journal: 2026-05-09 — Company2 Tenant Isolation Test

## Goal for the Session

Verify that VAML Inc (company2) is fully isolated from DSP Test Company (company1). Specifically:
- A VAML admin cannot read DSP employees, trucks, schedule, or dispatch data
- A VAML admin can read and write their own company's data
- Per-company config access controls work correctly
- Creating resources from a VAML token scopes them to VAML

---

## Hypothesis

Because all routers were converted during the multi-tenant migration (ADR-063/064/079) to filter on `caller.company_id`, a VAML admin token should return only VAML data from every endpoint. Cross-tenant access attempts should return 403 or 404. There should be no endpoint that returns data from a different company.

**Expected results summary:**
- `GET /employees` → 1 result (VAML admin only)
- `GET /trucks` → 0 results (VAML has no trucks yet)
- `GET /dispatch/{today}` → 200 with empty `assigned_crews`
- `GET /employees/{DSP_ADMIN_ID}` → 403 or 404
- `POST /trucks` → creates a VAML-scoped truck
- `PATCH /companies/my-config` → updates only VAML config
- `PATCH /companies/my-config` with `invite_expiry_days` → 403 (super admin only field)

---

## Setup

### Step 1 — Verify VAML company state

```python
# Check companies, configs, and admin accounts in the DB
companies = db.query(Company).all()
for c in companies:
    cfg = db.query(CompanyConfig).filter_by(company_id=c.id).first()
    admins = db.query(Employee).filter_by(company_id=c.id, role='admin').all()
```

Findings:
- VAML Inc (`9f2a5620-badd-4d3f-abbc-e2436e000204`) had 1 admin: Nicardo Hunt
- VAML `is_configured = False` — blocked all API access via `require_configured` middleware

### Step 2 — Check Cognito user status

```python
resp = client.list_users(UserPoolId=pool_id, Filter='username = "nicardo.hunt"')
```

Nicardo Hunt was `CONFIRMED` in Cognito with `cognito_sub = 114b5560-a081-70e3-1f83-79c83b094643`.

### Step 3 — Unlock VAML for testing

Two things were needed:
1. Set a known test password via `admin_set_user_password` (permanent, no challenge) so we could get an access token
2. Seed VAML `CompanyConfig` with platform defaults and set `is_configured = True`

For `is_configured`, the platform requires all 15 fields in `_REQUIRED_FIELDS` to be non-null before flipping the flag. We copied DSP's values as representative defaults:

```python
for f in _REQUIRED_FIELDS:
    setattr(vaml_cfg, f, getattr(dsp_cfg, f))
vaml_cfg.is_configured = True
db.commit()
```

> **Note:** In production, the VAML admin would complete setup via the Company Settings page (`/settings`), which calls `PATCH /companies/my-config` until all required fields are filled. `is_configured` flips automatically when the last required field is set. The only exception is `invite_expiry_days`, which is super-admin-only and must be set via the super admin UI.

### Step 4 — Obtain a VAML access token

```python
resp = client.initiate_auth(
    ClientId=app_client_id,
    AuthFlow='USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': 'nicardo.hunt', 'PASSWORD': 'TestPass123!'},
)
token = resp['AuthenticationResult']['AccessToken']
headers = {'Authorization': f'Bearer {token}'}
```

---

## Test Execution

All requests were made against `http://localhost:8000/api/v1` using the VAML admin token.

### Test 1 — Identity: `/employees/me`

**Request:** `GET /api/v1/employees/me`
**Expected:** 200, `role=admin`, employee belongs to VAML
**Actual:** ✓ 200, `role=admin`, `id=f194babf-ef59-4dcd-a299-31072bab68a2`

The token resolves to the correct employee via the `cognito_sub` fast path in `_resolve_employee_from_cognito`.

---

### Test 2 — Employee list isolation: `/employees`

**Request:** `GET /api/v1/employees`
**Expected:** 200, exactly 1 result (only VAML admin)
**First actual:** ✗ 200, **100 results** — DSP employees were leaking

**Root cause:** `GET /` in `employees.py` used `RoleChecker` (Cognito group validation) but resolved no `Employee` object and had **no `company_id` filter** on the query:

```python
# Before (broken):
def get_all_employees(
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    ...
):
    q = db.query(Employee)  # ← no company scope!
```

`RoleChecker` validates that the caller has the right Cognito group claim but does NOT resolve the DB employee or provide `company_id`. Every other list endpoint used `get_caller_employee` which does both.

**Fix:** Replaced `RoleChecker` dependency with `get_caller_employee`, added `Employee.company_id == caller.company_id` filter:

```python
# After (fixed):
def get_all_employees(
    caller: Employee = Depends(get_caller_employee),
    ...
):
    q = db.query(Employee).filter(Employee.company_id == caller.company_id)
```

The role check is implicitly handled — `get_caller_employee` returns the resolved employee, and `PRIVILEGED_ROLES` logic downstream still works because `caller.role` is the DB role.

**Second actual:** ✓ 200, exactly 1 result (VAML admin only)

---

### Test 3 — Cross-tenant employee read by ID

**Request:** `GET /api/v1/employees/{DSP_ADMIN_ID}`
**Expected:** 403 or 404
**Actual:** ✓ 404 `{"detail":"Employee not found"}`

The employee router's `GET /{employee_id}` filters by `Employee.company_id == caller.company_id`, so a VAML caller looking up a DSP ID gets a 404 (row exists in DB but is invisible through the scoped query).

---

### Test 4 — Truck isolation

**Request:** `GET /api/v1/trucks`
**Expected:** 200, 0 trucks (VAML has none)
**Actual:** ✓ 200, `[]`

DSP's 7 trucks were not visible.

---

### Test 5 — Create a truck, verify scope, delete

**Request:** `POST /api/v1/trucks` with `{"name": "TEST-001", "license_plate": "TEST-001", "capacity": 4}`
**Expected:** truck created, scoped to VAML
**Actual:** ✓ 201 (test initially expected 200 — status code was a test error, not a bug)

Subsequent `GET /trucks` returned 1 truck. After `DELETE /trucks/{id}` (returns 204), `GET /trucks` returned 0 again. Isolation confirmed.

**Test error noted:** Initial test payload used `truck_number` instead of `name` (422 validation error). Corrected to match the `TruckCreate` schema.

---

### Test 6 — Dispatch isolation

**Request:** `GET /api/v1/dispatch/{today}`
**Expected:** 200 with empty `assigned_crews` (no dispatch run for VAML today)
**Actual:** ✓ 200, `{"date": "...", "assigned_crews": {}, "warnings": []}`

The dispatch router filters by `TruckAssignment.company_id == caller.company_id`. With no assignments for VAML, it returns the empty shell — not a 404. This is correct behavior (dispatch was run, but empty).

---

### Test 7 — Schedule

**Request:** `GET /api/v1/schedule/{vaml_admin_id}?start_date={today}&end_date={today}`
**Expected:** 200 with Available status (no off-days set)
**Actual:** ✓ 200, `[{"date": "...", "status": "Available", "truck_name": null, "crew": null}]`

Initial test used the wrong URL shape (no `start_date` query param, got 422). Corrected.

---

### Test 8 — Notifications

**Request:** `GET /api/v1/notifications/{vaml_admin_id}`
**Expected:** 200 with empty list
**Actual:** ✓ 200, `[]`

Initial test used `GET /notifications` (no employee ID) which doesn't exist — 404. Corrected to match the actual route shape.

---

### Test 9 — Company config read

**Request:** `GET /api/v1/companies/my-config`
**Expected:** 200, `is_configured=true`
**Actual:** ✓ 200, full config with platform defaults

---

### Test 10 — Company config write

**Request:** `PATCH /api/v1/companies/my-config` with `{"rating_window_hours": 8}`
**Expected:** 200, updated value reflected
**Actual:** ✓ 200, `rating_window_hours=8`

---

### Test 11 — Super-admin-only field blocked

**Request:** `PATCH /api/v1/companies/my-config` with `{"invite_expiry_days": 30}`
**Expected:** 403
**Actual:** ✓ 403, `"'invite_expiry_days' can only be changed by a super admin."`

---

## Final Results

| Test | Result |
|---|---|
| `/me` returns VAML admin | ✓ |
| `/employees` returns only VAML employees | ✓ (after bug fix) |
| VAML employees contain no DSP admin ID | ✓ |
| Cross-tenant employee read blocked | ✓ |
| `/trucks` empty for VAML | ✓ |
| Can create + verify + delete a VAML truck | ✓ |
| `/dispatch` empty for VAML (correct 200) | ✓ |
| `/schedule` available for VAML admin | ✓ |
| `/notifications` empty for VAML | ✓ |
| `/companies/my-config` readable | ✓ |
| Config PATCH updates VAML config | ✓ |
| Super-admin field blocked for company admin | ✓ |

**12/12 real checks passed** (3 test expectation errors fixed along the way)

---

## Bug Found and Fixed

### Critical: `GET /employees` missing tenant scope

- **File:** `backend/app/routers/employees.py`, line ~249
- **Severity:** Critical — cross-tenant data leak
- **Root cause:** Route used `RoleChecker` (validates Cognito groups) instead of `get_caller_employee` (resolves the DB employee + company). Without a resolved employee, there was no `company_id` to filter on.
- **Fix:** Replaced `RoleChecker` with `get_caller_employee`; added `Employee.company_id == caller.company_id` to the query.
- **How to detect this class of bug:** Any router `GET /` list endpoint that uses `RoleChecker` instead of `get_caller_employee` will be missing tenant scope. After a multi-tenant migration, audit all list endpoints to confirm they filter by `caller.company_id`.

---

## Key Takeaways

### 1. `RoleChecker` vs `get_caller_employee` — different things
`RoleChecker` validates that the Cognito JWT contains the right group claim. It does NOT resolve a DB employee row and does NOT provide `company_id`. `get_caller_employee` does both. Use `get_caller_employee` (not `RoleChecker`) for any endpoint that must be company-scoped. `RoleChecker` alone is only appropriate for super-admin-style endpoints where there is intentionally no company scope.

### 2. `require_configured` blocks all API access, including setup
The `require_configured` middleware raises 503 if the company's `is_configured = False`. This includes the initial setup experience — a brand-new company cannot use the API at all until a super admin sets `is_configured = True` (via super admin UI or directly in the DB for testing). The self-service `PATCH /companies/my-config` endpoint is exempt from this middleware and can always be reached.

### 3. Test against the actual API shape
Status codes matter: trucks return 201 (Created), DELETE returns 204 (No Content). Routes that require query params (schedule needs `start_date`) will 422 without them. Always read the router code or OpenAPI docs before assuming a route shape. A 422 from a test is a test bug, not necessarily a server bug.

### 4. How to isolate tenant tests without a UI
1. `admin_set_user_password` (Cognito) to set a known password — `Permanent=True` so no challenge
2. `initiate_auth` with `USER_PASSWORD_AUTH` flow to get an access token
3. Include `Authorization: Bearer {token}` on all requests
4. Compare results to DB state via direct queries to confirm what the API should show

### 5. Audit approach after a multi-tenant migration
After converting a monorepo to multi-tenant, the right validation is an end-to-end test logged in as a user from each tenant — not just unit tests on individual endpoints. The employees bug would not have been caught by reading the code alone — `RoleChecker` looks correct at a glance. A live cross-tenant test was the only way to surface it.
