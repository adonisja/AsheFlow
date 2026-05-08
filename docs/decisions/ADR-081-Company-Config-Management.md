# ADR-081 — Company Config Management (Multi-Tenant Step 6)

**Date:** 2026-05-08  
**Status:** Accepted  
**Context:** Multi-tenant provisioning — Step 6 of `MULTITENANT_PLAN.md`

---

## Context

After Steps 1–5 provisioned the tenant pipeline (company creation, bootstrap, super admin UI), operational parameters were still hardcoded in `constants.py`. Every tenant shared the same shift times, training thresholds, and dispatch weights. The `CompanyConfig` model had columns for all of them but they were never populated — the null-fallback pattern was in place but no endpoints existed to set values.

Step 6 adds two access paths to `CompanyConfig`:

1. **Super admin** — can read and write any company's config, including the platform-level `invite_expiry_days`
2. **Company admin** — can read and write their own company's config; `invite_expiry_days` is locked out

---

## Decision

### Endpoints added

**Super admin (on `router`, prefix `/admin/companies`)**:
- `PATCH /admin/companies/{company_id}/config` — write any field for any company

**Company admin (on `company_admin_router`, prefix `/companies`)**:
- `GET /companies/my-config` — read own config
- `PATCH /companies/my-config` — write own config, `invite_expiry_days` blocked

### PATCH semantics — `exclude_unset=True`

Config updates use `payload.model_dump(exclude_unset=True)`. Only fields explicitly included in the request body are written. Fields absent from the payload are not touched, not zeroed. This is true PATCH semantics — the caller doesn't need to resend values they don't want to change.

### Null-fallback pattern preserved

All `CompanyConfig` fields start null at provisioning time. Services read them as:
```
value = company_config.field or DEFAULT_CONSTANT
```
Admins only need to set values that differ from platform defaults. No migration required for the seed company.

### Field-level authorization via `_SUPER_ADMIN_ONLY_FIELDS`

A frozenset of field names (`{"invite_expiry_days"}`) is checked inside `_apply_config_update`. If a company admin passes any of these fields, the function raises 403 before any write. This is enforced at the application layer rather than the schema layer so the field can still be read from the config response — it's only blocked on write for non-super-admins.

### Time fields as strings

SQLAlchemy stores `shift_start` etc. as `datetime.time`. The API accepts `"HH:MM"` strings and returns `"HH:MM"` strings. Conversion is done in `_parse_time` (input) and `CompanyConfigResponse.from_orm_obj` (output). Frontend uses `type="text"` inputs with `HH:MM` placeholders.

### Frontend

`CompanySettings.tsx` at `/settings` — company admin only. Six sections with plain-English field labels and descriptions:
- Shift Timing
- Crew Requirements
- Training Rules
- Dispatch Weights
- Walker Rating
- Driver Check-ins

`invite_expiry_days` is not rendered in the company admin UI (locked field, not just disabled — no reason to show it and confuse non-technical admins).

---

## Alternatives considered

**Schema-level enforcement (different `CompanyConfigUpdate` per role):** Two Pydantic models — one with `invite_expiry_days`, one without. Rejected because it creates serialization divergence; a single schema with application-layer enforcement is simpler and the error message is explicit.

**Merge at read time in the service layer:** Have services read config and merge with constants at query time. Rejected — the existing null-fallback pattern is already simpler and avoids adding a merge step to every service.

---

## Consequences

- Company admins can self-serve operational tuning without a super admin ticket
- `invite_expiry_days` is protected from accidental misconfiguration by non-super-admins
- All config fields have human-readable labels and descriptions in the UI
- The backend is ready for a second tenant with different operational rules
