# ADR-080 — Multi-Tenant Provisioning & Super Admin Identity

**Date:** 2026-05-08  
**Status:** Accepted — Steps 1–4 complete, Steps 5–6 pending

## Context

After completing Phase 1 (schema) and Phase 2 (router isolation), the system had company_id on every table and all queries scoped by tenant — but no way to actually create a tenant through the API. The only company in the system was the seed company inserted directly into the DB. There was also no platform-level identity that could act across tenants.

This ADR covers the design and implementation of the provisioning layer: how new DSP companies are onboarded, how the first admin for each company is bootstrapped, and how the super admin identity works.

## Decisions

### Super admin identity

A `super_admin` Cognito group was added to the existing user pool (precedence 1, above `admin` at 10). The platform owner's Cognito account is manually added to this group. No separate pool, no separate infrastructure — the existing JWT verification already extracts `cognito:groups`.

The super admin has **no Employee row**. The existing `get_caller_employee` dependency would 403 them because it requires an Employee record. A separate `get_super_admin` dependency was added that reads only the JWT groups and never touches the employees table.

### Company UUID

Generated server-side via `uuid.uuid4()` on creation. Immutable after creation — it is the foreign key for every row in the system.

### CompanyConfig provisioning

A blank `CompanyConfig` row (all fields null) is created atomically with the Company row. Services read config as `company_config.field or DEFAULT_CONSTANT` — null means "use the platform default". This means the seed company and all new companies work correctly from day one without any config data.

### First admin bootstrap

A dedicated `POST /admin/companies/{id}/bootstrap` endpoint handles the circular dependency (you need a company admin to invite employees, but you need to invite someone to become the first admin). The super admin provides a name and email; the endpoint creates an Employee row and sends an invite token. The first admin registers through the standard `/register?token=...` flow — no special path.

Bootstrap is idempotent: calling it again with the same email re-issues the invite token rather than creating a duplicate employee. `invite_sent: bool` in the response tells the caller whether email delivery succeeded — on failure the token is still valid and the endpoint can be retried.

### Company admin config editing

Company admins can edit their own `CompanyConfig` (Step 6, not yet built). `invite_expiry_days` is locked to super admin only — it affects token security posture, not operational tuning. All other fields are admin-editable with plain-English descriptions in the frontend.

### Super admin frontend

Lives at `/superadmin`, separate route and layout from the company admin dashboard. Not mixed into the existing admin UI.

## What was built (Steps 1–4)

**Step 1 — Cognito group:** `super_admin` group already existed in the pool at precedence 1. No action needed.

**Step 2 — `get_super_admin` dependency (`app/api/deps.py`):**
```python
def get_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "super_admin" not in current_user.get("cognito_groups", []):
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return current_user
```

**Step 3 — Companies router (`app/routers/companies.py`):**
- `POST /admin/companies` — creates Company + blank CompanyConfig in one transaction; enforces slug uniqueness and URL-safety (`^[a-z0-9-]+$`)
- `GET /admin/companies` — list all tenants
- `GET /admin/companies/{id}` — single company with full config (time fields serialized to "HH:MM" strings)
- `PATCH /admin/companies/{id}/deactivate` — sets `is_active=False`, no data deleted
- `PATCH /admin/companies/{id}/reactivate` — restores inactive company

**Step 4 — Bootstrap endpoint (`POST /admin/companies/{id}/bootstrap`):**
- Creates Employee with `role="admin"`, `account_status="pending_verification"`, `is_active=False`
- Generates invite token, sends invite email via existing `send_invite_email()`
- Returns `invite_sent: bool` — failure does not roll back the token
- Idempotent on email: re-issues token for existing non-active employee rather than creating duplicate

## Consequences

- A new DSP company can now be onboarded entirely through the API: create company → bootstrap first admin → admin registers → admin invites their employees
- Super admin actions leave no `company_id` on audit log rows (the `audit_logs.company_id` is intentionally nullable for this reason, per the model comment)
- `get_super_admin` is the only dependency safe to use on cross-tenant endpoints — never mix it with `get_caller_employee` on the same endpoint
- The seed company (`a0000000-0000-0000-0000-000000000001`) continues to work unchanged
