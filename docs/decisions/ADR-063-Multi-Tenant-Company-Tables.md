# ADR-063: Multi-Tenant Foundation — Company, CompanyConfig, and CompanyZone Tables

**Date:** 2026-05-07
**Status:** Implemented

## Context

AsheFlow was built as a single-tenant system — every table assumed one company,
all thresholds were hardcoded constants, and no row-level isolation existed.
The decision was made to support multiple Amazon DSP companies under one
deployment, with strict data separation and per-company configurability.

Three architectural questions were resolved before writing code:

1. **Isolation strategy**: single database with `company_id` on every table
   (chosen over schema-per-tenant and database-per-tenant due to scale — under
   10 companies expected in year one).
2. **Role hierarchy**: per-company `admin` + a global `super_admin` tier for
   the AsheFlow platform owner, with a hard tenant wall at the service layer.
3. **Config strategy**: all hardcoded operational constants move to a
   `company_configs` table; NULL means "not yet configured" and the backend
   falls back to the legacy hardcoded default until set via the admin UI.

## Decision

Create three new tables as Phase 1 of the multi-tenant migration:

- **`companies`** — master company record (name, slug, DSP code, timezone)
- **`company_configs`** — all configurable operational values per company
  (shift times, crew requirements, training thresholds, dispatch weights)
- **`company_zones`** — geographic DSP zones with optional sub-zone nesting
  via `parent_zone_id` self-reference; `bounds` stored as GeoJSON JSONB

A seed row for the existing test DSP was inserted in the migration using all
values sourced from `docs/SEED_COMPANY_CONFIG.md` — the captured live defaults
from the single-tenant version. This company ID is
`a0000000-0000-0000-0000-000000000001`.

All existing tables will gain a `company_id` FK in subsequent migrations
(Phase 1, Steps 2-3).

## Files changed

- `backend/app/models/company.py` — new: Company, CompanyConfig, CompanyZone ORM models
- `backend/app/models/__init__.py` — added import for new models
- `backend/alembic/versions/h1a2b3c4d5e6_add_company_tables.py` — migration + seed
- `docs/SEED_COMPANY_CONFIG.md` — reference document for all seeded values

## Deferred table: `company_discord_config` (Phase 4)

A fourth table was identified but deferred to Phase 4 (company config screens).
Every Discord-specific value that is currently hardcoded in `bot/config.py` or
env vars must move here before a second company can be onboarded:

- `guild_id`, `drivers_channel_id`, `trainers_channel_id`, `invite_channel_id`
- Role snowflake IDs: admin, manager, dispatch, driver, trainer, walker, bot, base member
- `bot_service_account_username`, `confirmation_window_hours`

The backend also reads `DISCORD_DRIVERS_CHANNEL_ID` as a raw env var in
`anchor_points.py` — this must be resolved via company config lookup once the
table exists. Full spec in `docs/DISCORD_SERVER_CONFIG.md`.

## Consequences

- All future service functions must accept and filter by `company_id`
- The `super_admin` Cognito group bypasses tenant checks; all other roles are
  scoped to their company
- Config values read order: `company_configs` row → fallback to hardcoded
  constant in `constants.py` (maintains backward compatibility during rollout)
- Zone bounds are GeoJSON — no PostGIS required yet; spatial queries will need
  PostGIS when route optimization is implemented
