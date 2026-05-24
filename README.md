<p align="center">
  <img src="frontend/src/assets/logo-full.svg" alt="AsheFlow Logo" width="280" />
</p>

<p align="center">
  <strong>Crew Management & Intelligent Dispatch for Amazon DSP Operations</strong><br/>
  <sub>Multi-tenant · Role-scoped · Discord-integrated · Production on AWS</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/build-passing-brightgreen?style=flat-square" alt="Build" />
  <img src="https://img.shields.io/badge/tests-154%20passing-brightgreen?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/license-BSL%201.1-orange?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/status-production-success?style=flat-square" alt="Status" />
</p>

<p align="center">
  <a href="https://asheflow.com"><strong>🌐 Live App</strong></a> ·
  <a href="https://api.asheflow.com/api/v1/docs"><strong>📖 API Docs</strong></a> ·
  <a href="docs/ARCHITECTURE.md"><strong>📐 Architecture</strong></a> ·
  <a href="docs/LEARNING_GUIDE.md"><strong>📚 Learning Guide</strong></a>
</p>

---

> **Demo access:** [asheflow.com](https://asheflow.com) is gated behind managed accounts. A recorded walkthrough and demo tenant are planned — contact [akkeem.tyrell@student.mec.cuny.edu](mailto:akkeem.tyrell@student.mec.cuny.edu) for a live demo.

---

## What It Does

AsheFlow replaces manual scheduling spreadsheets and verbal coordination for Amazon DSP delivery crews with a structured, role-aware platform that covers the full shift lifecycle — from dispatch planning in the morning to walker ratings and fuel logs at end of day.

**Core capabilities:**

- **Intelligent Dispatch** — weighted algorithm resolving driver preferences (favorites/bans), recurring off-days, PTO, trainer-trainee pairing, and crew balance to generate daily truck assignments
- **Two-Phase Discord Flow** — crew DM confirmations after dispatch; a second "Post Final Crews" action publishes finalized assignments to Discord channels with authoritative pairings
- **Dispatch Confirmation System** — tracks each crew member's response (confirmed/declined/pending) with timestamps; trainer declines trigger automatic trainee reassignment
- **Field Operations** — full driver shift lifecycle: check-in, pre-trip inspection, departure, walker attendance + rating, fuel/mileage log, end-of-day return
- **Training Pipeline** — phase-based trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, trainer marks, and automated graduation
- **Two-Tier Package Routing** — Tier 1 tote verification at the station (polygon-based zone checks before trucks leave); Tier 2 walker sub-route generation at the anchor point (geographic clustering into per-walker route cards)
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system
- **Workforce Analytics** — dispatch fill rate, trainer load, ban override frequency, confirmation response times, walker performance leaderboard, driver bias detection, vehicle compliance trending, availability heatmaps
- **Role-Scoped Dashboards** — each of 8 roles lands on a purpose-built home page with self-view analytics panels
- **Audit Log** — system-wide action trail for management and admin review
- **Multi-Tenant Architecture** — each DSP company is a fully isolated tenant; one deployment serves multiple companies with zero data bleed
- **Super Admin Panel** — platform-level UI for provisioning tenants, bootstrapping admins, and configuring per-company Discord integration

---

## Tech Stack

<p align="left">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/AWS-232F3E?style=for-the-badge&logo=amazon-aws&logoColor=white" />
  <img src="https://img.shields.io/badge/Discord.py-5865F2?style=for-the-badge&logo=discord&logoColor=white" />
</p>

| Layer | Technology |
|---|---|
| Backend API | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Uvicorn |
| Database | PostgreSQL 15 · Alembic (60 migrations) · Redis 7 |
| Task Queue | Celery 5.3.6 · Redis broker |
| Auth | AWS Cognito (JWKS, short-TTL JWTs, revocation) |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS 3 · Axios |
| Bot | discord.py · Cognito service account |
| Infrastructure | Docker Compose · AWS EC2 · AWS SSM deploy · GitHub Actions CI/CD |
| Tests | pytest · 154 tests · SQLite in-memory fixtures |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   CLIENT LAYER                       │
│   Browser (React 19 + Tailwind)  │  Discord Server   │
└──────────────┬──────────────────────────┬────────────┘
               │ HTTPS / JWT              │ Bot DMs / Posts
┌──────────────▼──────────────────────────▼────────────┐
│                   AWS EDGE                            │
│        CloudFront CDN  ·  Cognito Auth                │
└──────────────┬──────────────────────────┬────────────┘
               │                          │
┌──────────────▼──────────┐  ┌────────────▼────────────┐
│    FastAPI Backend       │  │    discord.py Bot        │
│    (Uvicorn, 4 workers)  │  │    (per-guild routing)   │
│    /api/v1/ · 28 routers │  │    X-Internal-Secret     │
└──────────────┬───────────┘  └─────────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │           │
┌───▼───┐ ┌───▼───┐ ┌─────▼──────┐
│Postgres│ │ Redis │ │   Celery   │
│  DB   │ │ Cache │ │Worker+Beat │
└───────┘ └───────┘ └────────────┘

Multi-tenancy: every table with company-owned data carries company_id.
All endpoints scoped to caller.company_id — zero cross-tenant data access.
```

---

## Role Definitions

| Role | Who | Home Page | Key Access |
|---|---|---|---|
| `driver` | Vehicle operators | Field Ops | Shift tools, inspection history, schedule, incidents |
| `walker` | Package delivery on foot | Field Ops | Own performance panel, schedule, incidents |
| `trainer` | Senior staff training new hires | Trainer Dashboard | Trainee tasks, own marks/performance, schedule |
| `trainee` | New hires in training program | My Training | Training progress, schedule, incidents |
| `dispatch` | Scheduling coordinator | Dispatch Center | Run + finalize dispatch, operations analytics, schedule changes |
| `management` | Operations supervisor | Management Dashboard | Approval queues, reporting, analytics, trainee pipeline, vehicle compliance |
| `admin` | Tech lead / company administrator | Admin Dashboard | Full access — all dashboards, system tools, feedback inbox, override access |
| `super_admin` | Platform operator | Super Admin Panel | Cross-tenant management, provisioning, config — no company scope |

---

## Development Setup

<details>
<summary><strong>Prerequisites</strong></summary>

- Docker & Docker Compose
- AWS Cognito User Pool with a configured App Client (USER_PASSWORD_AUTH flow enabled)
- A Discord application with bot token (for the bot service)

</details>

<details>
<summary><strong>Quick Start</strong></summary>

**1. Clone the repo**
```bash
git clone https://github.com/adonisja/AsheFlow.git
cd AsheFlow
```

**2. Set environment variables**
```bash
cp .env.example .env
# Fill in all required values in .env, backend/.env, frontend/.env, bot/.env
# Generate secrets:
python -c "import secrets; print(secrets.token_hex(32))"
```

Required variables include: `POSTGRES_PASSWORD`, `SECRET_KEY`, `INTERNAL_SECRET`, Cognito pool/client IDs, Discord bot token. The stack will refuse to start if any of these are unset.

**3. Start the stack**
```bash
docker-compose up --build
```

**4. Run migrations and seed data**
```bash
docker exec -it asheflow_backend alembic upgrade head
docker exec -it asheflow_backend python seed.py
```

**5. Run tests**
```bash
docker exec -it asheflow_backend python -m pytest tests/ -v
```

**Available at:**
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

</details>

<details>
<summary><strong>Environment Variables Reference</strong></summary>

| File | Key Variables |
|---|---|
| `.env` (root) | `POSTGRES_PASSWORD`, `SECRET_KEY` |
| `backend/.env` | `DATABASE_URL`, `REDIS_URL`, `AWS_COGNITO_USER_POOL_ID`, `AWS_COGNITO_APP_CLIENT_ID`, `INTERNAL_SECRET` |
| `frontend/.env` | `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_API_BASE_URL` |
| `bot/.env` | `DISCORD_BOT_TOKEN`, `COGNITO_USERNAME`, `COGNITO_PASSWORD`, `INTERNAL_SECRET` |

See `.env.example` at the project root for a complete template.

</details>

---

## Tenant Provisioning Flow

New companies are onboarded through the super admin panel (`/superadmin/companies`):

1. **Create company** — name, slug, Amazon DSP code, timezone
2. **Bootstrap admin** — creates an `admin`-role employee and sends a Cognito invite email
3. **Admin registers** — follows the invite link, sets password + Discord snowflake ID
4. **Complete setup** — admin fills in operational config at `/settings`; `is_configured` flips `true` automatically once all required fields are set
5. **Discord integration** — super admin pastes guild/channel/role snowflake IDs into the Discord Integration card; bot serves the guild from that point forward

---

## API Surface

All endpoints live under `/api/v1/`. Auth required on every endpoint via AWS Cognito JWT Bearer token. Every list and write endpoint is scoped to `caller.company_id`.

<details>
<summary><strong>View all 28 routers</strong></summary>

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
| `/truck-zones` | Zone polygon CRUD, activate/deactivate | management, admin |
| `/walker-routes` | Sort, commit, trip status, difficulty flags, misroute resolution | dispatch, management, admin |
| `/companies` | My config read/write | admin (own company) |
| `/admin/companies` | Full tenant CRUD, bootstrap, config, Discord config | super_admin only |
| `/registration` | Token validation, account creation | unauthenticated (invite token required) |
| `/internal` | Guild config fetch | bot only (X-Internal-Secret header) |

</details>

---

## Pages

<details>
<summary><strong>View all 23 pages</strong></summary>

| Route | Roles | Purpose |
|---|---|---|
| `/` | all | Role-aware redirect to home page |
| `/dispatch` | dispatch, admin | Run dispatch, crew assignment, two-phase Discord flow |
| `/operations-analytics` | dispatch, management, admin | Fill rate, trainer load, ban override frequency, confirmation response times |
| `/schedule` | all field staff, management, admin | Personal calendar + PTO (field); approval queue + heatmap (management/admin) |
| `/field-ops` | driver, walker, admin | Driver shift tools + inspection history; own performance panel (walker) |
| `/incidents` | all field staff, dispatch, management, admin | Submit incidents; management resolve queue |
| `/preferences` | driver, walker, trainer, admin | Fav/ban manager, assignment change requests |
| `/schedule-changes` | all field staff, dispatch, admin | Submit schedule change requests; approval queue |
| `/trainer-dashboard` | trainer, admin | Trainee task checklists, continuation requests, performance tab |
| `/my-training` | trainee | Personal training progress and history |
| `/trainee-management` | management, admin | Training pipeline overview, active trainees |
| `/vehicle-compliance` | management, admin | Inspection failure trending, per-driver and per-truck heatmaps |
| `/walker-performance` | management, admin | Walker leaderboard, letter grades, driver bias detection |
| `/assets` | management, admin | Employee and truck CRUD, bulk import, resend invite |
| `/anchor-points` | management, admin | Staging area management, arrival/departure lifecycle |
| `/settings` | admin | Company operational config (shift times, dispatch weights, training rules) |
| `/admin` | admin | System overview, workforce breakdown, feedback inbox, roster, fleet grid |
| `/account` | authenticated | Personal account management |
| `/preferences` | authenticated | Notification and display preferences |
| `/register` | unauthenticated | Invite-token-gated account registration |
| `/superadmin/companies` | super_admin | All tenants list with bootstrap actions |
| `/superadmin/companies/:id` | super_admin | Company detail: identity, setup status, employees, config, Discord integration |

</details>

---

## Project Structure

<details>
<summary><strong>View full structure</strong></summary>

```
AsheFlow/
├── .env.example                 # Required variables template
├── LICENSE                      # Business Source License 1.1
├── backend/
│   ├── alembic/versions/        # 60 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_caller_employee, require_configured
│   │   ├── models/              # 32 SQLAlchemy models
│   │   ├── routers/             # 28 API routers under /api/v1/
│   │   │   └── internal.py      # Bot-facing endpoints (/internal/*), X-Internal-Secret auth
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic (proprietary algorithm files gitignored)
│   │   │   └── constants.py     # Role constants — single source of truth
│   │   └── tasks/               # Celery periodic tasks
│   ├── tests/                   # 154 pytest tests
│   │   ├── conftest.py          # SQLite in-memory fixture
│   │   └── services/            # test_run_dispatch, test_available_pool,
│   │                            #   test_graduate_trainees, test_analytics
│   ├── seed.py
│   └── requirements.txt
├── bot/
│   ├── cogs/                    # Slash command groups (dispatch, invite, setup)
│   ├── services/
│   │   ├── api_client.py        # Async HTTP client with Cognito token refresh
│   │   └── guild_config.py      # Per-company Discord config, 5-min TTL cache
│   ├── config.py
│   ├── main.py
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── api/                 # axiosClient (JWT interceptor)
│       ├── components/
│       │   ├── auth/            # Login, RoleGuard
│       │   ├── dashboard/       # Role-scoped dashboard views
│       │   ├── layout/          # Navbar (two-tier: TitleBar + NavStrip)
│       │   └── ui/              # MotionCard, StatCard, ConfirmDialog, ErrorBanner
│       ├── contexts/            # AuthContext, ThemeContext
│       ├── hooks/               # useConfirm, useDebounce, etc.
│       └── pages/               # 23 route pages
├── docs/
│   ├── LEARNING_GUIDE.md        # Accumulated design lessons
│   └── ARCHITECTURE.md          # Full system architecture
└── docker-compose.yml
```

</details>

---

## Development Roadmap

- [x] **Phase 1** — Data models, dispatch algorithm, core CRUD routers
- [x] **Phase 2** — AWS Cognito auth, RBAC, Alembic migrations, API versioning, dispatch overrides
- [x] **Phase 3** — Frontend: Vite + Tailwind, auth context, base pages
- [x] **Phase 4** — Field Ops (6 driver tools), training pipeline, incidents, crew rebalancing, notifications
- [x] **Phase 5** — Role architecture audit, dashboard split per role, 6 reporting endpoints, schedule change requests
- [x] **Phase 6** — Analytics pages, security audit, dispatch unit tests, feedback admin UI, bug fixes
- [x] **Phase 7** — Discord bot (DM confirmations, two-phase dispatch flow, crew channel posting), training system phase redesign, trainer marks, persistent dispatch confirmations, audit log, Celery infrastructure
- [x] **Phase 8** — Dispatch hardening (trainer-decline reassignment, UUID crash guard), ConfirmDialog wiring, two-tier navbar, role constants, structured logging, anchor points UI, shift ops
- [x] **Phase 9** — Multi-tenant architecture: per-company DB isolation, Cognito pool v2, invite-token registration, role protection guards, session security, registration UX
- [x] **Phase 10** — Super admin panel (tenant provisioning, company config, Discord integration card), Discord multi-guild, discord_id snowflake enforcement, tenant isolation hardening
- [ ] **Phase 11** — Two-tier package routing: Tier 1 tote zone verification (polygon-based, auto-triggered post-dispatch), Tier 2 walker sub-route generation (geographic clustering, fairness-weighted assignment, misroute resolution)
- [ ] **Phase 12** — Demo tenant + recorded walkthrough, notification center UI, E2E tests, staging environment, avatar image upload (S3)

---

## Key Design Decisions

Architectural decisions are documented internally (91 ADRs). Key areas covered:

- Weighted dispatch algorithm design and fill-order logic
- Discord bot architecture and two-phase dispatch flow
- Multi-tenant data model and `company_id` isolation strategy
- Super admin panel and tenant provisioning flow
- Per-company Discord config with one bot serving multiple guilds
- `RoleChecker` vs `get_caller_employee` and the tenant isolation audit rule
- Two-tier package routing architecture and geographic clustering design

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full system architecture.

---

## What's Left

- **Two-tier routing (Phase 11 in progress)** — tier1_verify service, TruckZone CRUD router, zone editor UI (Leaflet), fairness-based walker auto-assignment, Tier 1 misroute flagging
- **Notification center UI** — notifications are stored and served; no dedicated panel or unread count indicator yet
- **Demo access** — demo tenant with seeded data and a recorded walkthrough for client presentations
- **E2E tests** — pytest covers backend services; no browser-level tests for the React frontend
- **Staging environment** — CI pipeline has a commented-out staging deploy job; no staging EC2 provisioned yet

---

## Security

- **Auth:** AWS Cognito JWTs with JWKS key-rotation retry; short TTL + server-side revocation
- **Multi-tenancy:** every endpoint scoped to `caller.company_id` — no cross-tenant data access possible
- **Secrets:** zero hardcoded credentials in committed code; all secrets via environment variables and GitHub Actions secrets
- **Proprietary logic:** core algorithm files excluded from the public repository via `.gitignore`
- **Dependencies:** automated CVE audit on every push via `pip-audit` in CI

---

## License

This project is licensed under the [Business Source License 1.1](LICENSE).

- **Free for:** personal use, education, and internal evaluation
- **Not free for:** commercial use, hosting as a service, or redistribution without a signed commercial license agreement
- **Change date:** 2030-05-24 — converts to Apache 2.0 on that date
- **Commercial licensing:** contact [akkeem.tyrell@student.mec.cuny.edu](mailto:akkeem.tyrell@student.mec.cuny.edu)

> The source code is intentionally public for portfolio and evaluation purposes. Viewing and studying the code is permitted. Using it to build a competing product or service is not.

---

<p align="center">
  Built by <a href="https://github.com/adonisja">Akkeem Tyrell</a> · <a href="https://asheflow.com">asheflow.com</a>
</p>
