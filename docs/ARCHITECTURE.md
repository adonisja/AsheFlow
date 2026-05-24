# AsheFlow — Architecture

## Overview

AsheFlow is a multi-tenant B2B SaaS platform for Amazon DSP crew management and dispatch. It runs as a monolith (one FastAPI process) with a separate Celery worker process for background tasks and a standalone Discord bot service. All three share one PostgreSQL database and one Redis instance.

There is no mobile app, no GraphQL layer, no microservices split, and no API gateway. This is a deliberate choice — the platform serves a focused operational domain and the monolith keeps deployment, debugging, and feature development straightforward at this scale.

---

## System Diagram

```
┌─────────────────────────────────────────────────────┐
│                   CLIENT LAYER                       │
│   Browser (React 19 + Tailwind)  │  Discord Server   │
└──────────────┬──────────────────────────┬────────────┘
               │ HTTPS / JWT              │ Bot DMs / Posts
┌──────────────▼──────────────────────────▼────────────┐
│                   AWS EDGE                            │
│        CloudFront CDN  ·  Cognito (JWKS auth)        │
└──────────────┬──────────────────────────┬────────────┘
               │ REST /api/v1/            │ X-Internal-Secret
┌──────────────▼──────────┐  ┌────────────▼────────────┐
│    FastAPI Backend       │  │    discord.py Bot        │
│    Uvicorn (4 workers)   │  │    Per-guild routing     │
│    28 routers            │  │    Cognito svc account   │
└──────────────┬───────────┘  └─────────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │           │
┌───▼────┐ ┌──▼────┐ ┌────▼───────┐
│Postgres│ │ Redis │ │   Celery   │
│  15    │ │   7   │ │Worker+Beat │
│60 migr.│ │broker │ │async tasks │
└────────┘ └───────┘ └────────────┘
```

---

## Multi-Tenancy

**Strategy: shared database, row-level isolation via `company_id`.**

Every table with company-owned data has a `company_id` UUID column. No PostgreSQL RLS is used — isolation is enforced at the application layer.

**How it works in practice:**

1. Every authenticated request resolves to an `Employee` row via `get_caller_employee()` in `deps.py`.
2. That employee's `company_id` is the only tenant identifier used in queries — it never comes from the request body or URL.
3. The `require_configured` middleware blocks all API access for a company until its admin completes initial setup (`CompanyConfig.is_configured = True`).
4. Super admins (`super_admin` Cognito group) have no `company_id` — they operate cross-tenant via dedicated `/admin/companies` endpoints.

**Key invariant:** there is no way for a caller to query another company's data through normal API usage. The `company_id` filter is always derived from the verified JWT, never from user input.

---

## Authentication & Authorization

**Provider:** AWS Cognito (User Pool, `USER_PASSWORD_AUTH` flow)

**Token flow:**
1. Frontend authenticates via AWS Amplify → receives Cognito ID token (JWT)
2. ID token sent as `Authorization: Bearer <token>` on every request
3. `verify_cognito_token()` in `security.py` validates the JWT signature against Cognito's JWKS
4. JWKS public keys are cached in Redis (1-hour TTL) — shared across all Uvicorn worker processes; fetched fresh from Cognito on cache miss
5. Validated token claims are passed to `get_caller_employee()` which resolves the Cognito `sub` to an `Employee` row via a 3-step lookup chain: `cognito_sub` → `username` → `discord_id`

**Authorization:** `RoleChecker` dependency — declared per endpoint, raises 403 if the caller's role is not in the allowed list. Role strings are defined once in `services/constants.py` and imported everywhere.

**Bot auth:** The Discord bot authenticates as a `dispatch`-role service account using Cognito `USER_PASSWORD_AUTH`. It auto-refreshes its JWT before expiry. Bot-to-backend calls for internal data (guild config) use a separate `X-Internal-Secret` header on `/internal/*` endpoints — these never go through Cognito.

---

## Backend

**Framework:** FastAPI · **ORM:** SQLAlchemy 2.0 · **Validation:** Pydantic v2 · **Server:** Uvicorn

### Request lifecycle

```
Request
  → OAuth2PasswordBearer (extract token)
  → verify_cognito_token() (JWKS validation)
  → get_caller_employee() (DB lookup, company_id resolved)
  → RoleChecker (role assertion)
  → require_configured (company setup gate)
  → Route handler
  → Response
```

### Key patterns

- **`company_id` always from caller** — never from request body. Every write operation stamps `company_id` from `caller.company_id`.
- **Pydantic v2 schemas** — all request bodies validated; response models defined separately from DB models.
- **No cross-router imports** — routers import from `services/` and `models/` only, never from each other.
- **Audit log** — destructive and sensitive actions are logged to the `AuditLog` table with actor, action, and target.

### Celery tasks

Redis is the broker. Tasks run in a separate `celery_worker` container. `celery_beat` (prod only) handles periodic scheduling.

Current tasks:
- EOD shift reminders to drivers
- Dispatch confirmation alerts (post-dispatch DMs via bot)
- Training deadline escalation checks
- Invite token expiry cleanup

---

## Frontend

**Framework:** React 19 · **Language:** TypeScript · **Build:** Vite · **Styling:** Tailwind CSS 3

### Auth flow

AWS Amplify handles Cognito authentication client-side. On login, Amplify stores the JWT and injects it into every API call via the `axiosClient` interceptor (`src/api/axiosClient.ts`). `RoleGuard` components block route access client-side by role — the server always re-validates independently.

### Key patterns

- **`axiosClient` is the only permitted API import** — no direct `fetch` or `axios` calls outside this module.
- **`useConfirm` + `ConfirmDialog`** — all destructive actions (delete, clear, override) go through this hook. No `window.confirm` anywhere in the codebase.
- **`ThemeContext`** — dark/light mode, persisted to localStorage.
- **Two-tier Navbar** — `TitleBar` (role label, user menu) + `NavStrip` (page links, role-scoped). Defined in `components/layout/Navbar.tsx`.
- **Role-scoped dashboards** — each of the 8 roles lands on a purpose-built home page. The `/` route reads the caller's role and redirects accordingly.

---

## Discord Bot

**Framework:** discord.py · **Auth:** Cognito service account (auto-refreshing JWT)

The bot is a separate Docker service. It has no exposed port for external traffic — it only makes outbound calls to the FastAPI backend and listens for Discord events.

**Multi-guild:** one bot process serves all company Discord servers. Per-company guild/channel/role IDs are stored in `company_configs` and fetched at runtime with a 5-minute TTL in-memory cache keyed by `guild_id → company_id`. A guild with no matching config in the DB gets a graceful no-op.

**Capabilities:**
- Dispatch DM confirmations (individual crew member notifications)
- Crew channel posting (finalized assignments published to Discord)
- Employee invite flow (new hire onboarding DM)
- `/setup-channels` slash command for per-guild channel scaffolding

---

## Data Model

**60 Alembic migrations · 32 SQLAlchemy models**

### Core tables

```
companies
  └── company_configs          (1:1 — operational settings, Discord config)
  └── company_zones            (DSP coverage area definitions)

employees
  ├── employee_off_days
  ├── employee_relationships   (fav/ban list)
  ├── time_off_requests
  └── invite_tokens

trucks
  └── truck_assignments        (daily dispatch — one per truck per date)
  │     └── assignment_members (crew members on each assignment)
  └── truck_zones              (polygon-defined coverage zones per truck)

training
  ├── training_curriculum
  ├── training_records
  └── training_tasks

field_ops
  ├── check_ins
  ├── departures
  ├── walker_ratings
  ├── vehicle_inspections
  └── fuel_mileage_logs

walker_routes
  ├── walker_trips
  ├── location_difficulty_flags
  └── misrouted_package_flags

communications
  ├── notifications
  ├── feedback
  └── audit_logs

scheduling
  ├── schedule_change_requests
  ├── assignment_change_requests
  ├── dispatch_confirmations
  └── shift_sessions

station_ops
  ├── anchor_points
  ├── dock_assignments
  ├── station_arrivals
  ├── package_manifests
  ├── rts_reports
  └── station_handoffs
```

### Multi-tenancy invariant

Every table in the groups above (except `companies` itself) has either:
- A direct `company_id` column, or
- A FK to a parent that carries `company_id` (e.g. `assignment_members → truck_assignments → company_id`)

---

## Infrastructure

**Environment:** AWS EC2 (production) · Docker Compose (dev + prod)

### Docker services

| Service | Image | Role |
|---|---|---|
| `postgres` | postgres:15-alpine | Primary database |
| `redis` | redis:7-alpine | Celery broker + JWKS cache |
| `backend` | python:3.12-slim | FastAPI + Uvicorn (4 workers in prod) |
| `celery_worker` | python:3.12-slim | Async background task processor |
| `celery_beat` | python:3.12-slim | Periodic task scheduler (prod only) |
| `bot` | python:3.12-slim | Discord bot (no exposed port) |

### CI/CD

GitHub Actions pipeline on every push:

1. **Dependency CVE audit** — `pip-audit` against `requirements.txt`
2. **Backend tests** — `pytest` with SQLite in-memory, 154 tests
3. **Deploy to prod** (master only, after both pass) — AWS SSM `SendCommand` triggers `git pull + docker compose build + up` on the EC2 instance; no SSH key required

### Secrets management

- Zero hardcoded credentials in any committed file
- All secrets injected via environment variables at runtime
- CI secrets (EC2 instance ID, AWS credentials) stored in GitHub Actions secrets
- Proprietary algorithm files excluded from the public repository via `.gitignore`

---

## Security

| Concern | Approach |
|---|---|
| Auth | AWS Cognito JWTs; JWKS cached in Redis with 1-hr TTL and key-rotation retry |
| Session security | Short-lived tokens; server-side revocation via Redis |
| Tenant isolation | `company_id` always derived from verified JWT, never from request input |
| Role enforcement | `RoleChecker` dependency on every endpoint; `super_admin` has no company scope |
| Input validation | Pydantic v2 on all request bodies; string length limits on all user-facing fields |
| Secrets | No hardcoded credentials; `.env` files gitignored; CI uses GitHub Actions secrets |
| Dependencies | `pip-audit` CVE scan on every push |
| Proprietary logic | Core algorithm files gitignored; not included in public repository |

---

## Technology Choices

**FastAPI** — async-native, auto-generated OpenAPI docs at `/docs`, Pydantic v2 integration, dependency injection pattern maps cleanly to auth + tenant scoping.

**PostgreSQL 15** — JSONB for flexible schema fields (polygon coordinates, package manifests, Discord config), ACID guarantees for dispatch state, mature UUID support.

**Redis 7** — dual-purpose: Celery broker (task queue) and JWKS public key cache (shared across all Uvicorn worker processes).

**AWS Cognito** — handles password storage, email verification, invite flows, and JWT issuance. Removes the need to build and maintain credential infrastructure.

**Discord bot** — the target users (delivery crews) live in Discord. Meeting them where they are eliminates the need for a separate notification app or SMS service.

**Celery** — decouples time-sensitive API responses from slow background work (email sends, escalation checks, reminder scheduling) without introducing a separate message queue service beyond Redis.
