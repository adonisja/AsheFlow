# AsheFlow — Crew Management & Dispatch Platform

A full-stack multi-tenant B2B platform for delivery crew management, intelligent dispatching, field operations, workforce analytics, and Discord-integrated crew communications. Built with FastAPI, PostgreSQL, React, and a discord.py bot.

---

## What It Does

AsheFlow replaces manual scheduling spreadsheets and verbal coordination with a structured, role-aware system that covers the full shift lifecycle — from dispatch planning in the morning to walker ratings and fuel logs at the end of the day.

**Core capabilities:**
- **Intelligent Dispatch** — weighted algorithm that resolves driver preferences (favorites/bans), recurring off-days, PTO requests, trainer-trainee pairing, and crew balance constraints to generate daily truck assignments
- **Two-Phase Discord Flow** — crew members receive individual DM confirmations after dispatch (with explicit trainer↔trainee pairing info); a second "Post Final Crews" action publishes finalized assignments to Discord channels with authoritative pairings
- **Dispatch Confirmation System** — `DispatchConfirmation` table tracks each crew member's response (confirmed/declined/pending) with timestamps for response-time analytics; trainer declines trigger automatic trainee reassignment with dispatch notifications
- **Field Operations** — driver shift lifecycle: check-in, pre-trip inspection, departure, walker attendance + rating, fuel/mileage log, end-of-day return
- **Training Pipeline** — phase-based trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, trainer marks, and automated graduation with Discord DM notification
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system (add days, drop days, or full rework)
- **Workforce Analytics** — operations analytics (dispatch fill rate, trainer load, ban override frequency, confirmation response times), walker performance leaderboard, driver bias detection, vehicle compliance trending, and availability heatmaps
- **Role-Scoped Dashboards** — each role lands on a purpose-built home page with self-view analytics panels (trainer marks, walker performance, driver inspection history)
- **Audit Log** — system-wide action trail for management and admin review
- **Multi-Tenant Architecture** — each DSP company is a fully isolated tenant; one deployment serves multiple companies with zero data bleed between them
- **Super Admin Panel** — platform-level UI for provisioning new tenants, bootstrapping admins, configuring per-company operational parameters, and managing Discord integration per guild

---

## Role Definitions

| Role | Who | Home Page | Key Access |
|---|---|---|---|
| `driver` | Vehicle operators | Field Ops | Field Ops (shift tools + own inspection history), Schedule, Preferences, Schedule Changes, Incidents |
| `walker` | Package delivery on foot | Field Ops | Field Ops (own performance panel), Schedule, Preferences, Schedule Changes, Incidents |
| `trainer` | Senior staff training new hires | Trainer Dashboard | Trainer Dashboard (trainee tasks + own marks/performance tab), Schedule, Preferences, Schedule Changes, Incidents |
| `trainee` | New hires in training program | My Training | Schedule, My Training, Schedule Changes, Incidents |
| `dispatch` | Scheduling coordinator | Dispatch Center | Dispatch Center (run + finalize), Operations Analytics, Schedule Changes, Incidents |
| `management` | Operations supervisor | Management Dashboard | Reporting dashboard, approval queues (PTO, off-days, schedule changes, assignment changes), Operations Analytics, Incidents, Trainee Management, Walker Performance, Vehicle Compliance |
| `admin` | Tech lead / company administrator | Admin Dashboard | Everything — all dashboards, system tools, feedback inbox, full override access |
| `super_admin` | Platform operator | Super Admin Panel | Cross-tenant company management, provisioning, config overrides — Cognito group, no company scope |

---

## Architecture

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL (Docker container)
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic (57 migrations)
- **Auth:** AWS Cognito (JWT verification via JWKS with key-rotation retry, `RoleChecker` + `get_caller_employee` dependency injection); all endpoints company-scoped via `caller.company_id`
- **Multi-tenancy:** every table with company-owned data has a `company_id` FK; `require_configured` middleware blocks API access until a company completes initial setup
- **Task Queue:** Celery + Redis (EOD reminders, dispatch alerts, training deadline checks, invite expiry cleanup)
- **Tests:** pytest — 96 tests across 4 service modules (run_dispatch, available_pool, graduate_trainees, analytics); SQLite in-memory with targeted schema fixtures

### Frontend
- **Framework:** React 18 + TypeScript (Vite)
- **Styling:** Tailwind CSS with custom design tokens; dark/light theme via ThemeContext
- **Auth:** AWS Cognito JWT (Amplify); role-based route guards (`RoleGuard`) block unauthorized access client-side; server always re-validates
- **API Client:** Axios with JWT interceptor (`axiosClient` — the only permitted import for API calls)
- **Confirm dialogs:** `useConfirm` hook + `ConfirmDialog` component — all destructive actions use this pattern; no `window.confirm` in the codebase

### Discord Bot
- **Framework:** discord.py (slash commands + webhook receiver)
- **Auth:** Cognito service account — bot authenticates as a `dispatch`-role user and auto-refreshes its JWT
- **Multi-guild:** one bot process serves all company Discord servers; per-company guild/channel/role IDs stored in `company_configs` DB table, fetched at runtime with a 5-minute TTL cache; graceful no-op for companies without Discord configured
- **Capabilities:** dispatch DM confirmations, crew channel posting, invite flow for new employees, `/setup-channels` slash command for per-guild channel scaffolding

### Infrastructure
- **Containerization:** Docker + Docker Compose (backend, frontend, postgres, redis, bot)
- **Seed data:** `backend/seed.py` and `backend/scripts/` for populated dev environments

---

## Project Structure

```
AsheFlow/
├── .env.example                 # Required variables template — copy to .env before starting
├── backend/
│   ├── alembic/versions/        # 57 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_caller_employee, require_configured
│   │   ├── models/              # SQLAlchemy models (25+ tables)
│   │   ├── routers/             # 26 API routers under /api/v1/
│   │   │   └── internal.py      # Bot-facing endpoints (/internal/*), X-Internal-Secret auth
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Dispatch algorithm, graduation, analytics, audit, company_config
│   │   │   └── constants.py     # Role constants — single source of truth for all role strings
│   │   └── tasks/               # Celery periodic tasks
│   ├── scripts/                 # Seed and utility scripts
│   ├── tests/
│   │   ├── conftest.py          # SQLite in-memory fixture (DISPATCH_TABLES)
│   │   └── services/            # test_run_dispatch, test_available_pool,
│   │                            #   test_graduate_trainees, test_analytics
│   ├── seed.py
│   └── requirements.txt
├── bot/
│   ├── cogs/                    # Slash command groups (dispatch, invite, setup)
│   ├── services/
│   │   ├── api_client.py        # Async HTTP client with Cognito token refresh
│   │   └── guild_config.py      # Per-company Discord config, 5-min TTL cache, guild→company map
│   ├── config.py                # Pydantic settings — bot token + internal secret only
│   ├── main.py                  # Bot entrypoint + webhook receiver
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                 # axiosClient (JWT interceptor)
│       ├── components/
│       │   ├── auth/            # Login, RoleGuard
│       │   ├── dashboard/       # DispatchView, ManagementView, etc.
│       │   ├── layout/          # Navbar (two-tier: TitleBar + NavStrip), SuperAdminLayout
│       │   └── ui/              # MotionCard, StatCard, SectionHeader, Skeleton,
│       │                        #   ThemeToggle, ConfirmDialog, ErrorBanner
│       ├── contexts/            # AuthContext, ThemeContext
│       ├── hooks/               # useConfirm, useDebounce, etc.
│       └── pages/               # 25 route pages
│           └── superadmin/      # Companies list + Company detail (super admin only)
├── docs/
│   ├── decisions/               # ADRs (ADR-001 through ADR-085)
│   ├── journals/                # Per-session development logs
│   ├── LEARNING_GUIDE.md        # Accumulated design lessons
│   ├── ANALYTICS_ACCESS_AUDIT.md
│   └── ARCHITECTURE.md
└── docker-compose.yml
```

---

## Development Setup

### Prerequisites
- Docker & Docker Compose
- AWS Cognito User Pool with a configured App Client (USER_PASSWORD_AUTH flow enabled)
- A Discord application with bot token (for the bot service)

### Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/adonisja/AsheFlow.git
   cd AsheFlow
   ```

2. **Set environment variables**
   - Copy `.env.example` → `.env` at the project root and fill in all required values
   - `backend/.env` — database URL, Cognito config, Celery settings, internal secret
   - `frontend/.env` — Cognito pool/client IDs, API base URL
   - `bot/.env` — Discord bot token, Cognito service account credentials, internal secret
   - Generate `SECRET_KEY` and `INTERNAL_SECRET` with: `python -c "import secrets; print(secrets.token_hex(32))"`
   - **Note:** the stack will refuse to start if `POSTGRES_PASSWORD`, `SECRET_KEY`, or `INTERNAL_SECRET` are unset

3. **Start the stack**
   ```bash
   docker-compose up --build
   ```

4. **Run migrations and seed data**
   ```bash
   docker exec -it asheflow_backend alembic upgrade head
   docker exec -it asheflow_backend python seed.py
   ```

5. **Run tests**
   ```bash
   docker exec -it asheflow_backend python -m pytest tests/ -v
   ```

**Available at:**
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

---

## Tenant Provisioning Flow

New companies are onboarded through the super admin panel (`/superadmin/companies`):

1. **Create company** — name, slug, Amazon DSP code, timezone
2. **Bootstrap admin** — creates an `admin`-role employee and sends a Cognito invite email
3. **Admin registers** — follows the invite link, sets password + Discord snowflake ID
4. **Complete setup** — admin fills in operational config at `/settings` (shift times, dispatch weights, training rules); `is_configured` flips `true` automatically once all required fields are set
5. **Discord integration** — super admin pastes guild/channel/role snowflake IDs into the Discord Integration card on the company detail page; bot serves the guild from that point forward

---

## API Surface

All endpoints live under `/api/v1/`. Authentication is required on every endpoint via AWS Cognito JWT Bearer token. Every list and write endpoint is scoped to `caller.company_id` — no cross-tenant data access is possible.

| Router | Endpoints | Access |
|---|---|---|
| `/employees` | CRUD, bulk import, deactivate, `/me`, resend invite | management, admin (write); authenticated (read own) |
| `/trucks` | CRUD, deactivate | management, admin |
| `/dispatch` | Run, assign, swap, clear, publish, finalize, confirmations | dispatch, admin |
| `/analytics` | Fill rate, trainer load, ban overrides, confirmation times | dispatch, management, admin |
| `/schedule` | View by employee, available by date, availability summary | authenticated |
| `/employee-off-days` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/time-off-requests` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/schedule-change-requests` | Submit, approve, reject, cancel | field staff, dispatch (submit); management, admin (review) |
| `/assignment-change-requests` | Submit, approve, reject, cancel | walker, trainer (submit); dispatch (review) |
| `/employee-relationships` | Fav/ban CRUD | driver, walker, trainer (own only); dispatch, management, admin (read) |
| `/field-ops` | Check-in, departure, return, inspection, rating, fuel log, walker profile | driver (submit); walker (own profile); management, admin (read) |
| `/incidents` | Submit, resolve, summary | all field staff (submit); management, admin (manage) |
| `/training` | Curriculum, records, tasks, pipeline summary | trainer, trainee, management, admin |
| `/trainer-marks` | Submit mark, `/mine`, `/mine/summary`, `/trainer/{id}` | trainer (own); management, admin (all) |
| `/trainer-coverage` | Coverage records | trainer, management, admin |
| `/notifications` | Read, mark read, clear | authenticated (own only) |
| `/feedback` | Submit, list, update status | authenticated (submit); admin (list, update) |
| `/audit` | System action log | management, admin |
| `/anchor-points` | Staging anchor CRUD, arrive/depart lifecycle | management, admin |
| `/shift-ops` | Active shift state, manifest acknowledgement | driver, management, admin |
| `/companies` | My config read/write | admin (own company) |
| `/admin/companies` | Full tenant CRUD, bootstrap, config, Discord config | super_admin only |
| `/registration` | Token validation, account creation | unauthenticated (invite token required) |
| `/internal` | Guild config fetch | bot only (X-Internal-Secret header) |

---

## Pages

| Route | Roles | Purpose |
|---|---|---|
| `/` | all | Role-aware redirect to home page |
| `/dispatch` | dispatch, admin | Run dispatch, crew assignment, two-phase Discord flow |
| `/operations-analytics` | dispatch, management, admin | Fill rate, trainer load, ban override frequency, confirmation response times |
| `/schedule` | all field staff, management, admin | Personal calendar + PTO (field); approval queue + heatmap (management/admin) |
| `/field-ops` | driver, walker, admin | Driver shift tools + inspection history (driver); own performance panel (walker); analytics (admin) |
| `/incidents` | all field staff, dispatch, management, admin | Submit incidents; management resolve queue |
| `/preferences` | driver, walker, trainer, admin | Fav/ban manager, assignment change requests; system-wide analytics (admin) |
| `/schedule-changes` | all field staff, dispatch, admin | Submit schedule change requests; analytics + approval queue (admin) |
| `/trainer-dashboard` | trainer, admin | Trainee task checklists, continuation requests, own performance tab |
| `/my-training` | trainee | Personal training progress and history |
| `/trainee-management` | management, admin | Training pipeline overview, active trainees |
| `/vehicle-compliance` | management, admin | Inspection failure trending, per-driver and per-truck heatmaps |
| `/walker-performance` | management, admin | Walker leaderboard, letter grades, driver bias detection, per-walker profiles |
| `/assets` | management, admin | Employee and truck CRUD, bulk import, resend invite |
| `/anchor-points` | management, admin | Staging area management, arrival/departure lifecycle |
| `/settings` | admin | Company operational config (shift times, dispatch weights, training rules) |
| `/admin` | admin | System overview, workforce breakdown, feedback inbox, roster, fleet grid |
| `/register` | unauthenticated | Invite-token-gated account registration (sets password + Discord ID) |
| `/superadmin/companies` | super_admin | All tenants list with bootstrap actions, has-admin status badge |
| `/superadmin/companies/:id` | super_admin | Company detail: identity, setup status, employees, config editor, Discord integration, danger zone |

---

## Development Roadmap

- [x] **Phase 1** — Data models, dispatch algorithm, core CRUD routers
- [x] **Phase 2** — AWS Cognito auth, RBAC (`RoleChecker`), Alembic migrations, API versioning, dispatch overrides
- [x] **Phase 3** — Frontend: Vite + Tailwind, auth context, base pages (Schedule, Preferences, Dashboard)
- [x] **Phase 4** — Field Ops (6 driver tools), training pipeline, incidents, crew rebalancing, notifications
- [x] **Phase 5** — Role architecture audit, dashboard split per role, 6 reporting endpoints, schedule change requests, tool scope enforcement
- [x] **Phase 6** — Analytics pages, security audit (ownership checks, schema validation, JWKS rotation, credential hygiene), dispatch unit tests, feedback admin UI, bug fixes
- [x] **Phase 7** — Discord bot (DM confirmations, two-phase dispatch flow, crew channel posting), training system phase-based redesign, trainer marks, persistent dispatch confirmations, audit log, Celery task infrastructure, analytics access audit + role-scoped fixes, test suite expansion
- [x] **Phase 8** — Dispatch hardening (trainer-decline reassignment, bumped-trainee fix, UUID crash guard, confirmation polling), ConfirmDialog wiring, two-tier navbar, truck name resolution, role constants, structured logging, docker-compose secret hardening, anchor points UI, shift ops
- [x] **Phase 9** — Multi-tenant architecture: per-company DB isolation (`company_id` on all tables), Cognito pool v2, federated login guard, invite-token registration flow, role protection guards, session security (short TTL + revocation), registration UX polish, bot startup auth resilience
- [x] **Phase 10** — Super admin panel (tenant provisioning, company config management, employee snapshot, Discord integration card), Discord multi-guild (per-company guild/channel/role IDs in DB, one bot serving all guilds), discord_id snowflake enforcement (migration + schema validators + frontend validation), tenant isolation hardening (`GET /employees` scope fix, bumped-trainee cross-tenant fix), super admin UI polish (has-admin badge, breadcrumb nav, no-admin empty state)

---

## Key Design Decisions

See [`docs/decisions/`](docs/decisions/) for full ADRs (ADR-001 through ADR-085). Highlights:

- **[ADR-002/003](docs/decisions/ADR-002-Dispatch-Algorithm-Design.md)** — weighted dispatch algorithm design and implementation
- **[ADR-039](docs/decisions/ADR-039-Discord-Bot-Phase1-Dispatch-Confirmation.md)** — Discord bot architecture and two-phase dispatch flow
- **[ADR-063/064](docs/decisions/ADR-063-Multi-Tenant-Company-Tables.md)** — multi-tenant data model and company_id isolation strategy
- **[ADR-080](docs/decisions/ADR-080-Multi-Tenant-Provisioning-SuperAdmin.md)** — super admin panel and tenant provisioning flow
- **[ADR-082](docs/decisions/ADR-082-Discord-Multi-Guild-Per-Company.md)** — per-company Discord config, one bot serving multiple guilds
- **[ADR-084](docs/decisions/ADR-084-Employee-List-Tenant-Scope-Fix.md)** — RoleChecker vs get_caller_employee and the tenant isolation audit rule

---

## What's Left

- **Notification center UI** — in-app notifications are stored and served; frontend surfaces them inline on dashboards but has no dedicated notification panel or unread count indicator
- **E2E tests** — pytest suite covers backend services; no browser-level tests exist for the React frontend
- **Company2 Discord wiring** — VAML Inc needs guild/channel/role snowflakes entered via super admin UI once a Discord server is provisioned for them
