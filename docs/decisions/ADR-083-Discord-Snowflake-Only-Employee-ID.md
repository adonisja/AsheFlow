# ADR-083 — Discord Snowflake-Only employee.discord_id

**Date:** 2026-05-09  
**Status:** Accepted

---

## Context

The `employees.discord_id` column (previously `VARCHAR(100)`) stored arbitrary strings. Seed data and legacy imports populated it with `name#discriminator` strings (e.g. `johndoe#1234`), placeholder strings like `discord_seed_1`, and genuine 17-19 digit Discord snowflake IDs. The Discord bot uses this column to DM employees and look them up by user ID — non-numeric values are useless to it and could cause API errors.

Discord deprecated the `name#discriminator` format in 2023. All current Discord user IDs are numeric snowflakes. Keeping the mixed format creates ambiguity and requires every consumer to defensively parse the field.

---

## Decision

### Database migration (`m4n5o6p7q8r9`)

Two steps run in a single Alembic revision:

1. `UPDATE employees SET discord_id = NULL WHERE discord_id IS NOT NULL AND discord_id !~ '^[0-9]+$'` — NULLs out all values that are not pure digit strings using a Postgres regex. This covers `name#discriminator` values, placeholder strings, and any future garbage.
2. `ALTER COLUMN discord_id TYPE VARCHAR(20)` — resizes from `VARCHAR(100)`. Discord snowflakes are 17-19 digits; 20 chars gives one digit of headroom. Existing numeric values fit with room to spare.

Data that was NULLed cannot be restored via downgrade — the downgrade only reverts the column type back to `VARCHAR(100)`.

### Backend schema validation

A shared `_validate_discord_id` helper is used by `field_validator("discord_id", mode="before")` in three schemas:

- `EmployeeCreate`
- `EmployeeUpdate`
- `BulkImportRow`

Behavior:
- `None` or empty string → `None` (coerced, not rejected)
- 17-20 digit string → accepted as-is
- Anything else → `ValueError` with a clear message

`BulkImportRow.discord_id` was changed from `str` (required) to `Optional[str]` — `discord_id` is not always known at bulk import time and employees can link via registration.

### Frontend validation

**Register.tsx** — added a format check (`/^\d{17,20}$/`) both as an inline hint shown while typing and as a submit-time guard with a descriptive error message pointing to Discord's Developer Mode.

**Assets.tsx** — edit form validates on change, blocks the submit step if the format is wrong. Employees with null `discord_id` show "not set" in amber in the roster table instead of a blank cell.

**BulkImportModal.tsx** — validation changed from "Required" to format-only (blank is allowed); column header updated from "Discord ID *" to "Discord Snowflake"; submit payload sends `null` for blank entries.

---

## Alternatives considered

**Validate at the bot layer only:** Let anything into the DB, reject at bot call time. Rejected — garbage data propagates silently and corrupts audit state before any error surface.

**Keep `name#discriminator` and resolve to snowflake via Discord API:** Possible in theory but requires an authenticated lookup per employee at write time, rate-limited by Discord. Rejected in favor of requiring the caller to supply the correct ID upfront.

---

## Consequences

- Employees whose `discord_id` was a `name#discriminator` or placeholder will have `NULL` after the migration and will need to re-enter it via Assets or registration
- All future writes are validated at the API layer before reaching the DB
- The bot can trust that any non-null `discord_id` is a usable numeric snowflake
- `VARCHAR(20)` enforces the invariant at the DB layer as a second line of defense
