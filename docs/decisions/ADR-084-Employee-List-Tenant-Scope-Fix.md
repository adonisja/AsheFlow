# ADR-084 — Employee List Endpoint Missing Tenant Scope Fix

**Date:** 2026-05-09  
**Status:** Accepted  
**Discovered via:** Company2 end-to-end isolation test

---

## Context

During the company2 isolation test, `GET /api/v1/employees` with a VAML Inc token returned all 100 DSP Test Company employees. This was a critical cross-tenant data leak.

The route used `RoleChecker` (validates Cognito group claims) as its auth dependency, not `get_caller_employee` (resolves the DB employee row and provides `company_id`). Without a resolved employee, there was no `company_id` to filter on, so the query returned all rows across all companies.

Every other list endpoint in the codebase used `get_caller_employee` correctly. This route was the outlier — it predated the multi-tenant migration and was not updated during the conversion.

---

## Decision

Replace `RoleChecker` with `get_caller_employee` as the primary auth dependency for `GET /employees`. Add `Employee.company_id == caller.company_id` to the query.

```python
# Before (broken):
def get_all_employees(
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    ...
):
    q = db.query(Employee)  # no company scope

# After (fixed):
def get_all_employees(
    caller: Employee = Depends(get_caller_employee),
    ...
):
    q = db.query(Employee).filter(Employee.company_id == caller.company_id)
```

The role-based logic that previously used `caller_groups` from `current_user` is replaced with `caller.role` from the resolved employee — equivalent information, already available.

---

## Why RoleChecker Alone Is Not Sufficient for Multi-Tenant Endpoints

`RoleChecker` checks the `cognito:groups` claim in the JWT. It answers: "does this user have the right Cognito group?" It does NOT resolve a DB row. It does NOT provide `company_id`. It is appropriate for:

- Super-admin endpoints (intentionally company-agnostic)
- Endpoints where Cognito group membership is the only gate (no company scope needed)

`get_caller_employee` answers: "who is this person in the DB, and which company do they belong to?" It should be used for every endpoint that must be company-scoped.

---

## Audit Implication

Any endpoint using `RoleChecker` that also returns company-owned data should be audited for missing tenant scope. After this fix, `GET /employees` is the only known instance — all other list endpoints already used `get_caller_employee`.

---

## Consequences

- `GET /employees` is now correctly scoped to the caller's company
- A VAML token returns only VAML employees; a DSP token returns only DSP employees  
- The `include_inactive` guard now uses `caller.role` instead of `caller_groups` — functionally identical
- Management role filter (`PROTECTED_ROLES`) now uses `caller.role == "management"` instead of group membership — same semantics, consistent with the rest of the router
