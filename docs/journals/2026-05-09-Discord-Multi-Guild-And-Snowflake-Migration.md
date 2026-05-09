# Engineering Journal: 2026-05-09

## Goal for the Session

1. Migrate Discord config (guild/channel/role IDs) from `bot/.env` into the `company_configs` DB table so a single bot process can serve multiple Discord servers
2. Enforce numeric-only (snowflake) Discord IDs on the `employees.discord_id` column — remove the legacy `name#discriminator` strings

---

## Problems Encountered

### 1. Bot crashed on startup after removing guild/channel/role fields from `bot/config.py`

**What happened:** After removing `discord_guild_id`, `discord_role_*`, etc. from the Pydantic `Settings` class in `bot/config.py`, the bot crashed at startup with `Extra inputs are not permitted`. The old `.env` file still had all the original `DISCORD_*` variables. Pydantic's default `extra = "forbid"` rejected them.

**Fix:** Added `extra = "ignore"` to the inner `Config` class. This silently drops any `.env` key not declared in `Settings` — the stale variables are harmless leftovers.

**Lesson:** When removing fields from a Pydantic settings model backed by an env file you don't fully control, always add `extra = "ignore"` before removing the fields. Otherwise the startup crash appears unrelated to the code change.

### 2. Super admin pages froze when navigating between companies

**What happened:** Clicking a company card in the super admin UI caused the page to visually freeze for ~1-2 seconds before loading.

**Root cause:** `SuperAdminLayout.tsx` wrapped `<Outlet />` in `AnimatePresence mode="wait"`. This mode holds the incoming page's render until the outgoing page's exit animation fully completes (~350ms). Combined with the loading skeleton's own transition, the effect compounded into an apparent freeze.

**Fix:** Removed `AnimatePresence`, `motion.div`, and all framer-motion imports from `SuperAdminLayout.tsx`. The super admin section has no visual need for cross-page animations.

### 3. Super admin pages stopped loading entirely after the AnimatePresence fix

**What happened:** After removing `AnimatePresence`, all super admin pages went blank and nothing loaded.

**Root cause:** When removing the `useLocation` import from the import line (it was used to key the `motion.div`), the `const location = useLocation();` call in the component body was left behind. At runtime, `useLocation` was `undefined`, causing a `ReferenceError` that crashed the entire layout.

**Fix:** Removed `const location = useLocation();` from the component body.

**Lesson:** When stripping an import, grep the file for all usage sites before saving. The import line is the visible half; call sites in the body are easy to miss.

---

## Solutions & Procedures

### Discord multi-guild migration

1. Created Alembic migration `l3m4n5o6p7q8` — adds 13 BigInteger nullable columns to `company_configs`
2. Updated `CompanyConfig` ORM model and `get_discord_config()` service function
3. Created `GET /internal/guild-config/{company_id}` bot-facing endpoint with `X-Internal-Secret` auth
4. Created `bot/services/guild_config.py` with 5-min TTL cache and `_guild_to_company` reverse map
5. Updated all webhook callers in `dispatch.py`, `trucks.py`, `anchor_points.py`, `tasks/dispatch_alerts.py`, and `api/deps.py` to pass `company_id`
6. Rewrote all bot cogs (`dispatch.py`, `invite.py`, `setup.py`) to accept `company_id` and fetch config from the service
7. Added `DiscordConfigCard` to the super admin company detail page

### Snowflake-only discord_id

1. Queried live DB — found ~95% of `discord_id` values were `name#discriminator` seed data; 2 real snowflakes
2. Created and ran Alembic migration `m4n5o6p7q8r9` — NULLed non-numeric values, resized column to `VARCHAR(20)`
3. Added `_validate_discord_id` shared validator to `EmployeeCreate`, `EmployeeUpdate`, and `BulkImportRow` schemas
4. Updated `BulkImportModal.tsx`, `Assets.tsx`, and `Register.tsx` with format validation

---

## Key Takeaways

- **One bot token, many guilds:** Discord allows a single bot to be a member of multiple guilds simultaneously. The only constraint is that guild/channel/role IDs must be per-guild — there's no concept of "shared" channels across servers. The per-company DB config pattern maps cleanly onto this.
- **`extra = "ignore"` is a safe escape hatch for env migration:** When transitioning away from env vars to DB-backed config, the env file usually can't be cleaned up atomically. `extra = "ignore"` lets you remove the setting from code without requiring a simultaneous env file change.
- **`AnimatePresence mode="wait"` is blocking by design:** It's useful for sequential page transitions but actively harmful in layouts where the incoming page's data fetch should start immediately. Use `mode="popLayout"` or no mode for layouts where speed matters.
- **Always grep for call sites, not just import lines:** A missing import shows up at parse time; a `ReferenceError` on a stale call site only shows up at runtime in the specific branch that exercises it.
