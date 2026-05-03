# AsheFlow — Crew Management & Dispatch Platform

A full-stack B2B platform for delivery crew management, intelligent dispatching, field operations, workforce analytics, and Discord-integrated crew communications. Built with FastAPI, PostgreSQL, React, and a discord.py bot.

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
| `admin` | Tech lead / developer | Admin Dashboard | Everything — all dashboards, system tools, feedback inbox, full override access |

---

## Architecture

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL (Docker container)
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic (37 migrations)
- **Auth:** AWS Cognito (JWT verification via JWKS with key-rotation retry, `RoleChecker` dependency injection)
- **Task Queue:** Celery + Redis (EOD reminders, dispatch alerts, training deadline checks, invite expiry cleanup)
- **Tests:** pytest — 97 tests across 4 service modules (run_dispatch, available_pool, graduate_trainees, analytics); SQLite in-memory with targeted schema fixtures

### Frontend
- **Framework:** React 18 + TypeScript (Vite)
- **Styling:** Tailwind CSS with custom design tokens + DaisyUI component layer
- **Auth:** AWS Amplify + Cognito Federated Identity (Discord SSO)
- **API Client:** Axios with JWT interceptor (`axiosClient` — the only permitted import for API calls)

### Discord Bot
- **Framework:** discord.py (slash commands + webhook receiver)
- **Auth:** Cognito service account — bot authenticates as a `dispatch`-role user and auto-refreshes its JWT
- **Capabilities:** dispatch DM confirmations, crew channel posting, invite flow for new employees

### Infrastructure
- **Containerization:** Docker + Docker Compose (backend, frontend, postgres, redis, bot)
- **Seed data:** `backend/seed.py` and `backend/scripts/` for populated dev environments

---

## Project Structure

```
AsheFlow/
├── .env.example                 # Required variables template — copy to .env before starting
├── backend/
│   ├── alembic/versions/        # 37 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_current_user, get_caller_employee
│   │   ├── models/              # SQLAlchemy models (20+ tables)
│   │   ├── routers/             # 20 API routers under /api/v1/
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Dispatch algorithm, graduation, analytics, audit
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
│   ├── services/api_client.py   # Async HTTP client with Cognito token refresh
│   ├── config.py                # Pydantic settings (reads from bot/.env)
│   ├── main.py                  # Bot entrypoint + webhook receiver
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                 # axiosClient (JWT interceptor)
│       ├── components/
│       │   ├── auth/            # Login
│       │   ├── layout/          # Navbar (two-tier: TitleBar + NavStrip), Layout
│       │   └── ui/              # MotionCard, StatCard, SectionHeader, Skeleton, ThemeToggle, ConfirmDialog
│       ├── contexts/            # AuthContext, ThemeContext
│       └── pages/               # 20+ route pages
├── docs/
│   ├── decisions/               # ADRs (ADR-001 through ADR-059)
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
- AWS Cognito User Pool with a configured App Client
- A Discord application with bot token (for the bot service)

### Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/adonisja/AsheFlow.git
   cd AsheFlow
   ```

2. **Set environment variables**
   - Copy `.env.example` → `.env` at the project root and fill in all required values
   - `backend/.env` — database URL, Cognito config, Celery settings
   - `frontend/.env` — see `frontend/.env.template`
   - `bot/.env` — Discord bot token, Cognito service account credentials, internal secret
   - All need `AWS_COGNITO_USER_POOL_ID`, `AWS_COGNITO_CLIENT_ID`, and `AWS_REGION`
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

## API Surface

All endpoints live under `/api/v1/`. Authentication is required on every endpoint via AWS Cognito JWT Bearer token. Ownership checks are enforced on all personal-data endpoints.

| Router | Endpoints | Access |
|---|---|---|
| `/employees` | CRUD, deactivate, `/me` | management, admin (write); authenticated (read own) |
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
| `/anchor-points` | Staging anchor CRUD | management, admin |

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
| `/assets` | management, admin | Employee and truck CRUD |
| `/admin` | admin | System overview, workforce breakdown, feedback inbox, roster, fleet grid |

---

## Development Roadmap

- [x] **Phase 1** — Data models, dispatch algorithm, core CRUD routers
- [x] **Phase 2** — AWS Cognito auth, RBAC (`RoleChecker`), Alembic migrations, API versioning, dispatch overrides
- [x] **Phase 3** — Frontend: Vite + Tailwind, auth context, base pages (Schedule, Preferences, Dashboard)
- [x] **Phase 4** — Field Ops (6 driver tools), training pipeline, incidents, crew rebalancing, notifications
- [x] **Phase 5** — Role architecture audit, dashboard split per role, 6 reporting endpoints, schedule change requests, tool scope enforcement
- [x] **Phase 6** — Analytics pages, security audit (ownership checks, schema validation, JWKS rotation, credential hygiene), dispatch unit tests, feedback admin UI, bug fixes
- [x] **Phase 7** — Discord bot (DM confirmations, two-phase dispatch flow, crew channel posting), training system phase-based redesign, trainer marks, persistent dispatch confirmations, audit log, Celery task infrastructure, analytics access audit + role-scoped fixes, test suite expansion (97 tests)
- [x] **Phase 8** — Dispatch hardening: trainer-decline auto-reassignment with dispatch notifications, trainer/trainee pairing notifications (in-app + bot DMs), bumped-trainee data loss fix, UUID crash guard, confirmation polling staleness indicator, ConfirmDialog wiring across all destructive dispatch actions, two-tier responsive navbar, truck name resolution in Today's Dispatch card, role constants centralisation, structured logging across publish/curriculum/reassign flows, docker-compose secret hardening + `.env.example`

---

## What's Left

- **TruckAssignment lifecycle** — hook the existing `status` field (`planned → active → completed`) into departure and return events so the management dashboard can show real-time fleet status
- **Anchor points** — staging area management tied to truck lifecycle (model and router exist; UI not yet wired)
- **Notification center UI** — in-app bell notifications are stored and served but the frontend has no dedicated notification panel; currently surfaced only inline on dashboards
- **E2E tests** — pytest suite covers backend services; no browser-level tests exist for the React frontend
