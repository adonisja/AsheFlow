# 2026-05-08 — Multi-Tenant Provisioning & Super Admin (Steps 1–4)

## What prompted this

After Phase 2 (router isolation) completed, all queries were scoped by company_id but there was no way to create a new tenant through the API. The seed company was the only tenant, inserted directly into the DB. There was also no platform-level identity — `admin` was the highest role and it was company-scoped.

The work in this session establishes the provisioning layer: how the platform owner creates new DSP companies and bootstraps their first admin.

## What was discovered during audit

- `super_admin` Cognito group already existed at precedence 1 in the active pool (`us-east-2_SvVO2ofAb`) — nothing to create
- `Company`, `CompanyConfig`, `CompanyZone` models were well-designed but had no router and were not registered in `main.py`
- `get_caller_employee` would 403 a super admin because it requires an Employee row
- The `audit_logs.company_id` is intentionally nullable (documented in the model) — covers super admin cross-tenant actions

## Architectural decisions locked

All decisions were discussed and agreed before implementation:

- Single Cognito pool — `super_admin` group in existing pool, no separate infrastructure
- Super admin has no Employee row — ever
- `get_super_admin` dependency: JWT only, never touches employees table
- `/superadmin` frontend: separate route, separate layout
- Company admins edit their own config; `invite_expiry_days` locked to super admin only
- DB config overrides `constants.py` when non-null (null-fallback pattern)
- Bootstrap sends invite token — first admin uses standard registration flow
- Company UUID is immutable after creation

## Step 2 — `get_super_admin`

Added to `app/api/deps.py` between `get_caller_employee_optional` and `class Pagination`. 15 lines. Reads `cognito:groups` from the JWT claims dict returned by `get_current_user`, raises 403 if `super_admin` not present, returns the full claims dict.

## Step 3 — Companies router

New file `app/routers/companies.py`. Five endpoints:

`POST /admin/companies` — The key design point: `db.flush()` after adding the Company row so the UUID is populated before the CompanyConfig FK reference. Both rows committed atomically. Slug validated with `^[a-z0-9-]+$` regex at the Pydantic layer; duplicate slugs return 409.

`GET /admin/companies/{id}` — Returns `CompanyDetailResponse` which embeds `CompanyConfigResponse`. The config model has a `from_orm_obj` classmethod that handles SQLAlchemy `Time` objects → `"HH:MM"` string conversion, since the Pydantic `from_attributes` path can't do that automatically.

Deactivate/reactivate are idempotent-guarded (400 if already in the target state).

Registered in `main.py` alongside all other routers.

## Step 4 — Bootstrap endpoint

Added to the bottom of `companies.py` as a new section. The circular dependency problem: to invite the first admin you need an admin, but to get an admin you need to invite them. Solved by giving the super admin a dedicated endpoint that doesn't require an existing company employee.

Key design choices:
- **Idempotent**: same email called twice → re-issues token, doesn't create duplicate employee. This matters because email delivery can fail silently.
- **`invite_sent: bool`**: the response tells the super admin whether SES delivery succeeded. On failure the token is still valid in the DB — just call the endpoint again.
- **No Cognito account created here**: the endpoint only creates the Employee row and sends the invite. Cognito account creation happens in `POST /registration/complete` when the admin completes their registration form. One code path for all Cognito accounts.
- **account_status stays `pending_verification`**: `get_caller_employee` flips it to `active` on first successful login — same as every other employee.

## Result

97/97 tests passing. Full provisioning pipeline now works end-to-end:
1. Super admin calls `POST /admin/companies` → company + blank config created
2. Super admin calls `POST /admin/companies/{id}/bootstrap` → invite sent to first admin
3. First admin opens `/register?token=...` → registers normally
4. First admin logs in → `account_status` flips to `active`
5. First admin invites their employees via existing `POST /registration/invite`
