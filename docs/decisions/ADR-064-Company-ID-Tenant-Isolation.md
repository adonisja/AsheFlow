# ADR-064: Add company_id to All Tenant-Scoped Tables

**Date:** 2026-05-07
**Status:** Implemented

## Context

Phase 1, Step 2 of the multi-tenant migration. With the `companies` table in
place, every existing table needed a `company_id` foreign key to enable
row-level tenant isolation.

## Decision

Added `company_id UUID NOT NULL` to all 32 tenant-scoped tables via a single
Alembic migration with three steps: add nullable, backfill, set NOT NULL.

`audit_logs` is the one exception — it keeps `company_id` nullable with no FK
constraint, because super_admin actions cross company boundaries and the actor
may not belong to any company.

All existing rows were backfilled with the seed company ID
`a0000000-0000-0000-0000-000000000001`.

All ORM model files were updated in the same step to add the `company_id`
column definition, keeping models and DB schema in sync.

## Files changed

- `backend/alembic/versions/h2b3c4d5e6f7_add_company_id_to_all_tables.py`
- All 26 model files under `backend/app/models/` (excluding base.py and company.py)

## Consequences

- The DB schema is now multi-tenant ready at the storage layer
- No service layer changes yet — queries still run without `company_id` filters
  (Phase 1, Steps 4-7 will add those)
- `training_curriculums` is now per-company, meaning each company can have its
  own curriculum. The existing curriculum rows are assigned to the seed company.

## Composite unique constraints on `employees` (implemented same session)

`discord_id` and `email` were changed from globally unique to
`UNIQUE(company_id, discord_id)` and `UNIQUE(company_id, email)` in migration
`h4d5e6f7g8h9`. The `email` partial index excludes NULLs. Both the ORM model
`__table_args__` and the duplicate checks in `routers/employees.py` (single
create and bulk import) were updated to scope by `caller.company_id`.

## audit_logs special rule — must not be changed

`audit_logs.company_id` is nullable with **no FK constraint**. This is load-bearing
and must stay that way. Two scenarios make a strict FK impossible:

1. **super_admin cross-company actions** — the platform owner acts on Company A's
   data but belongs to no company. There is no honest single `company_id` to
   enforce via FK.
2. **System-generated actions** — Celery jobs (invite expiry cleanup, auto-graduation)
   write audit rows with `actor_id = NULL` and have no natural `company_id` to
   constrain at the DB layer.

The column is still populated for all normal company-scoped actions so it remains
queryable. The service layer must always pass the correct `company_id` when writing
audit rows for company-scoped actions — Postgres will not catch omissions the way
a FK constraint would. If you are ever tempted to add the FK, re-read this note first.
