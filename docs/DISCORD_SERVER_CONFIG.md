# Discord Server Configuration — DSP Test Company

All Discord IDs are server-specific and stored in `bot/.env` (gitignored).
In the multi-tenant architecture these move to a `company_discord_config` table
so each company has its own server, channels, and role IDs.

**Bot token and all Discord IDs are stored in `bot/.env` — not here.**

---

## Server (Guild)

| Item | Config key |
|---|---|
| Guild ID | `DISCORD_GUILD_ID` in `bot/.env` |

---

## Named Channels

| Purpose | Config key |
|---|---|
| Drivers chat — assignment cards posted here | `DISCORD_DRIVERS_CHANNEL_ID` |
| Trainers chat | `DISCORD_TRAINERS_CHANNEL_ID` |
| New employee invite landing channel | `DISCORD_INVITE_CHANNEL_ID` (defaults to drivers channel) |

**Per-truck channels:** each `Truck` DB record has a `discord_channel_id`
(BigInteger snowflake). These are set via the admin UI and stored directly on
the truck row — not listed here.

---

## Discord Server Role IDs

All role IDs are loaded from `bot/.env`. Required keys:

| Role name | Config key |
|---|---|
| `AsheFlow` (base member role) | `DISCORD_ROLE_ASHEFLOW` |
| `Admin` | `DISCORD_ROLE_ADMIN` |
| `Manager` | `DISCORD_ROLE_MANAGER` |
| `Dispatch` | `DISCORD_ROLE_DISPATCH` |
| `Driver` | `DISCORD_ROLE_DRIVER` |
| `Captain` (Trainer) | `DISCORD_ROLE_CAPTAIN` |
| `Walker` | `DISCORD_ROLE_WALKER` |
| `Bot` | `DISCORD_ROLE_BOT` |

---

## Bot Service Account

The Discord bot authenticates to the AsheFlow backend API as a Cognito user
with the `dispatch` role. Credentials stored in `bot/.env`.

| Item | Config key |
|---|---|
| Username | `BOT_USERNAME` in `bot/.env` |
| Password | `BOT_PASSWORD` in `bot/.env` |
| Role | `dispatch` |
| Cognito pool | `AWS_COGNITO_USER_POOL_ID` in `bot/.env` |
| App client | `AWS_COGNITO_CLIENT_ID` in `bot/.env` |

---

## Configurable operational values

| Item | Config key |
|---|---|
| Dispatch confirmation window | `CONFIRMATION_WINDOW_HOURS` in `bot/.env` |
| API base URL | `API_BASE_URL` in `bot/.env` |

---

## What needs a `company_discord_config` table (multi-tenant Phase 4)

When a second company is onboarded, the following must be per-company in DB:

- `guild_id` — their Discord server
- `drivers_channel_id`
- `trainers_channel_id`
- `invite_channel_id`
- `role_admin_id`, `role_manager_id`, `role_dispatch_id`, `role_driver_id`,
  `role_trainer_id`, `role_walker_id`, `role_bot_id`, `role_base_member_id`
- `bot_service_account_username` — each company's bot auth account
- `confirmation_window_hours` — may vary per company

Currently these are env vars in `bot/.env`. They must move to DB config before
a second company is onboarded.

**The `DISCORD_DRIVERS_CHANNEL_ID` env var in the backend (`anchor_points.py`)
is also hardcoded per-deployment — this must be resolved via company config
lookup using the caller's `company_id` once the config table exists.**

## `employees.discord_id` uniqueness — resolved

`discord_id` and `email` are now `UNIQUE(company_id, discord_id)` and
`UNIQUE(company_id, email)` — fixed during Phase 1 migration, not deferred.
See ADR-064 for details.
