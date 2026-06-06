<p align="center">
  <img src="frontend/src/assets/logo-full.svg" alt="AsheFlow Logo" width="280" />
</p>

<p align="center">
  <strong>Crew Management & Intelligent Dispatch for Amazon DSP Operations</strong><br/>
  <sub>Multi-tenant · Role-scoped · Discord-integrated · Mobile-first · Production on AWS</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/build-passing-brightgreen?style=flat-square" alt="Build" />
  <img src="https://img.shields.io/badge/tests-236%20passing-brightgreen?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/react_native-0.76-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React Native" />
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

AsheFlow replaces manual scheduling spreadsheets and verbal coordination for Amazon DSP delivery crews with a structured, role-aware platform that covers the full shift lifecycle — from dispatch planning in the morning to driver surveys and route sorting at end of day. A React web app handles management and dispatch; a React Native mobile app serves the field.

**Core capabilities:**

- **Intelligent Dispatch** — weighted algorithm resolving driver preferences (favorites/bans), recurring off-days, PTO, trainer-trainee pairing, and crew balance to generate daily truck assignments
- **Two-Phase Discord Flow** — crew DM confirmations after dispatch; a second "Post Final Crews" action publishes finalized assignments to Discord channels with authoritative pairings
- **Dispatch Confirmation System** — tracks each crew member's response (confirmed/declined/pending) with timestamps; trainer declines trigger automatic trainee reassignment
- **Field Operations** — full driver shift lifecycle: check-in, pre-trip inspection, departure, walker attendance + rating, fuel/mileage log, end-of-day return
- **Training Pipeline** — phase-based trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, trainer marks, Phase 4 observation forms, and a graduation quiz gate
- **Two-Tier Package Routing** — Tier 1 route sort at the station (polygon-based zone checks, per-trainer sort interface); Tier 2 walker sub-route generation at the anchor point (geographic clustering into per-walker route cards, fairness-weighted assignment)
- **Location Profiles** — two-tier location knowledge base: company-managed profiles with a global library for promotion; cold-start bulk creation; block-key-based routing integration
- **Driver Surveys** — end-of-shift feedback from trainers and walkers; management activates per-day, 4 yes/no questions + notes, visual results with per-question % bars and individual drill-down
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system
- **Gear Requests** — field staff request equipment; management review and fulfilment tracking
- **Workforce Analytics** — dispatch fill rate, trainer load, ban override frequency, confirmation response times, walker performance leaderboard, driver bias detection, vehicle compliance trending, availability heatmaps
- **Role-Scoped Dashboards** — each of 8 roles lands on a purpose-built home page with self-view analytics panels
- **Notification Inbox** — in-app notifications with expiry; 20+ typed notifications across all workflows; Discord DM mirroring for time-sensitive alerts
- **Audit Log** — system-wide action trail for management and admin review
- **Multi-Tenant Architecture** — each DSP company is a fully isolated tenant; one deployment serves multiple companies with zero data bleed
- **Super Admin Panel** — platform-level UI for provisioning tenants, bootstrapping admins, and configuring per-company Discord integration

---

## Tech Stack

<p align="left">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/React_Native-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/AWS-232F3E?style=for-the-badge&logo=amazon-aws&logoColor=white" />
  <img src="https://img.shields.io/badge/Discord.py-5865F2?style=for-the-badge&logo=discord&logoColor=white" />
</p>

| Layer | Technology |
|---|---|
| Backend API | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Uvicorn |
| Database | PostgreSQL 15 · Alembic (88 migrations) · Redis 7 |
| Auth | AWS Cognito (JWKS, short-TTL JWTs, revocation) |
| Web Frontend | React 19 · TypeScript · Vite · Tailwind CSS 3 · Axios |
| Mobile App | React Native 0.76 · Expo · TypeScript · React Navigation |
| Bot | discord.py · Cognito service account |
| Infrastructure | Docker Compose · AWS EC2 · AWS SSM deploy · GitHub Actions CI/CD |
| Tests | pytest · 236 tests · SQLite in-memory fixtures |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                            │
│  Browser (React 19 + Tailwind)  │  Mobile (React Native 0.76) │
│                                 │  Discord Server              │
└──────────────┬──────────────────────────┬──────────────────────┘
               │ HTTPS / JWT              │ Bot DMs / Posts
┌──────────────▼──────────────────────────▼──────────────────────┐
│                         AWS EDGE                                │
│          CloudFront CDN  ·  Cognito Auth                        │
└──────────────┬──────────────────────────┬──────────────────────┘
               │                          │
┌──────────────▼──────────┐  ┌────────────▼────────────┐
│    FastAPI Backend       │  │    discord.py Bot        │
│    (Uvicorn, 4 workers)  │  │    (per-guild routing)   │
│    /api/v1/ · 36 routers │  │    X-Internal-Secret     │
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

| Role | Who | Web Home | Mobile Access |
|---|---|---|---|
| `driver` | Vehicle operators | Field Ops | Field Ops, Anchor Points, Preferences, Schedule, Incidents, Location Profiles |
| `walker` | Package delivery on foot | Field Ops | Field Ops, Walker Dashboard, Schedule, Incidents, Preferences, Location Profiles |
| `trainer` | Senior staff training new hires | Trainer Dashboard | Training, Route Sort, Schedule, Incidents, Preferences, Location Profiles, Driver Survey |
| `trainee` | New hires in training program | My Training | My Training, Schedule, Incidents, Preferences, Location Profiles |
| `dispatch` | Scheduling coordinator | Dispatch Center | Schedule Changes |
| `management` | Operations supervisor | Management Dashboard | Schedule Changes |
| `admin` | Tech lead / company administrator | Admin Dashboard | Full access — all field and management tabs |
| `super_admin` | Platform operator | Super Admin Panel | N/A — web only |

---

## Development Setup

<details>
<summary><strong>Prerequisites</strong></summary>

- Docker & Docker Compose
- Node.js 20+ (for the mobile app and frontend)
- AWS Cognito User Pool with a configured App Client (USER_PASSWORD_AUTH flow enabled)
- A Discord application with bot token (for the bot service)
- Expo CLI (for the mobile app)

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
# Fill in all required values in .env, backend/.env, frontend/.env, mobile/.env, bot/.env
# Generate secrets:
python -c "import secrets; print(secrets.token_hex(32))"
```

Required variables include: `POSTGRES_PASSWORD`, `SECRET_KEY`, `INTERNAL_SECRET`, Cognito pool/client IDs, Discord bot token. The stack will refuse to start if any of these are unset.

**3. Start the backend stack**
```bash
docker-compose up --build
```

**4. Run migrations and seed data**
```bash
docker exec -it asheflow_backend alembic upgrade head
docker exec -it asheflow_backend python seed.py
```

**5. Start the mobile app**
```bash
cd mobile && npm install && npx expo start
```

**6. Run tests**
```bash
docker exec -it asheflow_backend python -m pytest tests/ -v
```

**Available at:**
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Mobile: Expo dev server (scan QR with Expo Go or run on simulator)

</details>

<details>
<summary><strong>Environment Variables Reference</strong></summary>

| File | Key Variables |
|---|---|
| `.env` (root) | `POSTGRES_PASSWORD`, `SECRET_KEY` |
| `backend/.env` | `DATABASE_URL`, `REDIS_URL`, `AWS_COGNITO_USER_POOL_ID`, `AWS_COGNITO_APP_CLIENT_ID`, `INTERNAL_SECRET` |
| `frontend/.env` | `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_API_BASE_URL` |
| `mobile/.env` | `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_COGNITO_USER_POOL_ID`, `EXPO_PUBLIC_COGNITO_APP_CLIENT_ID` |
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
<summary><strong>View all 36 routers</strong></summary>

| Router | Endpoints | Access |
|---|---|---|
| `/employees` | CRUD, bulk import, deactivate, promote/demote, `/me`, resend invite | management, admin (write); authenticated (read own) |
| `/trucks` | CRUD, deactivate | management, admin |
| `/dispatch` | Run, assign, swap, clear, publish, finalize, confirmations | dispatch, admin |
| `/truck-assignments` | Read assignments by date, swap members | dispatch, admin |
| `/assignment-members` | Member-level reads | dispatch, management, admin |
| `/truck-transfers` | Record and view mid-day truck transfers | dispatch, management, admin |
| `/analytics` | Fill rate, trainer load, ban overrides, confirmation times | dispatch, management, admin |
| `/schedule` | View by employee, available by date, availability summary | authenticated |
| `/employee-off-days` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/time-off-requests` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/schedule-change-requests` | Submit, approve, reject, cancel | field staff, dispatch (submit); management, admin (review) |
| `/assignment-change-requests` | Submit, approve, reject, cancel | walker, trainer (submit); dispatch (review) |
| `/employee-relationships` | Fav/ban CRUD | driver, walker, trainer (own only); dispatch, management, admin (read) |
| `/field-ops` | Check-in, departure, return, inspection, rating, fuel log, walker profile | driver (submit); walker (own profile); management, admin (read) |
| `/shift-sessions` | Active session state, heartbeat | driver, management, admin |
| `/shift-ops` | Manifest acknowledgement, manifest state | driver, management, admin |
| `/incidents` | Submit, resolve, summary | all field staff (submit); management, admin (manage) |
| `/training` | Curriculum, records, tasks, pipeline summary | trainer, trainee, management, admin |
| `/continuation-requests` | Submit and review trainer continuation requests | trainer (submit); management, admin (review) |
| `/trainee-credentials` | Record and verify trainee-specific credentials | trainer, management, admin |
| `/trainer-marks` | Submit mark, `/mine`, `/mine/summary`, `/trainer/{id}` | trainer (own); management, admin (all) |
| `/trainer-coverage` | Coverage records | trainer, management, admin |
| `/graduation-quiz` | Issue quiz, submit response, review, graduate | trainee (submit); management, admin (issue, review, graduate) |
| `/driver-surveys` | Activate survey, submit response, detail + stats | management, admin (activate, view); trainer, walker (respond) |
| `/sort` | Route sort sessions, commit sort, per-trainer sort state | trainer, dispatch, admin |
| `/location-profiles` | Company location profiles CRUD, block-key tags | management, admin (write); all field roles (read) |
| `/location-profile-library` | Global library profiles, promote to company | management, admin |
| `/anchor-points` | Staging anchor CRUD, arrive/depart lifecycle | management, admin |
| `/gear-requests` | Submit, review, fulfil gear requests | field staff (submit); management, admin (review) |
| `/notifications` | Read, mark read, clear, prune expired | authenticated (own only) |
| `/feedback` | Submit, list, update status | authenticated (submit); admin (list, update) |
| `/audit` | System action log | management, admin |
| `/companies` | My config read/write | admin (own company) |
| `/admin/companies` | Full tenant CRUD, bootstrap, config, Discord config | super_admin only |
| `/registration` | Token validation, account creation | unauthenticated (invite token required) |
| `/internal` | Guild config fetch, Discord role sync | bot only (X-Internal-Secret header) |

</details>

---

## Web Pages

<details>
<summary><strong>View all 34 routes</strong></summary>

| Route | Roles | Purpose |
|---|---|---|
| `/login` | unauthenticated | Login with username/password or Discord/Google OAuth |
| `/register` | unauthenticated | Invite-token-gated account registration |
| `/setup` | admin | First-run setup wizard |
| `/` | all | Role-aware redirect to role home page |
| `/dispatch-home` | dispatch, admin | Dispatch home — today's assignment grid overview |
| `/dispatch` | dispatch, admin | Run dispatch, crew assignment, two-phase Discord flow |
| `/operations-analytics` | dispatch, management, admin | Fill rate, trainer load, ban override frequency, confirmation response times |
| `/schedule` | all field staff, management, admin | Personal calendar + PTO (field); approval queue + heatmap (management/admin) |
| `/schedule-changes` | all field staff, dispatch, admin | Submit schedule change requests; approval queue |
| `/field-ops` | driver, walker, trainer, trainee, dispatch, management, admin | Driver shift tools + inspection history; own performance panel (walker) |
| `/incidents` | all field staff, dispatch, management, admin | Submit incidents; management resolve queue |
| `/preferences` | authenticated | Fav/ban manager, assignment change requests, notification preferences |
| `/account` | authenticated | Personal account management |
| `/trainer-dashboard` | trainer, admin | Trainee task checklists, continuation requests, performance tab |
| `/phase4-observation` | trainer, admin | Phase 4 observation form for trainer-submitted trainee field assessments |
| `/my-training` | trainee | Personal training progress and history |
| `/my-quiz` | trainee | Graduation quiz — submit and track attempt status |
| `/trainee-management` | management, admin | Training pipeline overview, active trainees |
| `/graduation-quiz/:quizId` | management, admin | Review and score a submitted graduation quiz |
| `/training-curriculum` | management, admin | Manage the training phase curriculum |
| `/vehicle-compliance` | management, admin | Inspection failure trending, per-driver and per-truck heatmaps |
| `/walker-performance` | management, admin | Walker leaderboard, letter grades, driver bias detection |
| `/trainer-marks` | management, admin | Trainer performance marks and history |
| `/driver-surveys` | management, admin | Activate surveys, view response rates, per-question stats, individual drill-down |
| `/sort` | trainer, dispatch, admin | Route sort interface — per-trainer sort sessions, commit sort |
| `/walker-sort` | driver, dispatch, admin | Walker sub-route sort and assignment at the anchor point |
| `/location-profiles` | all roles | Location knowledge base — view, add, tag block keys |
| `/anchor-points` | driver, dispatch, management, admin | Staging area management, arrival/departure lifecycle |
| `/gear` | all roles | Submit and track gear requests |
| `/assets` | management, admin | Employee and truck CRUD, bulk import, resend invite |
| `/settings` | admin | Company operational config (shift times, dispatch weights, training rules) |
| `/admin` | admin | System overview, workforce breakdown, feedback inbox, roster, fleet grid |
| `/feedback` | admin | Feedback inbox and resolution queue |
| `/superadmin/companies` | super_admin | All tenants list with bootstrap actions |
| `/superadmin/companies/:id` | super_admin | Company detail: identity, setup status, employees, config, Discord integration |

</details>

---

## Mobile App

The mobile app targets field staff — drivers, walkers, trainers, and trainees. Built with React Native 0.76 + Expo, it uses a horizontal scrollable tab bar that renders only the tabs relevant to the authenticated user's role.

<details>
<summary><strong>View all mobile screens</strong></summary>

| Screen | Roles | Purpose |
|---|---|---|
| Home | all | Today's assignment summary, quick-nav to key tools |
| Today's Assignment | all | Full assignment detail for the current day |
| Field Ops | driver, walker, trainer, trainee | Driver shift tools — check-in, inspection, departure, return, fuel log |
| Walker Dashboard | walker | Own performance metrics, rating history |
| Training | trainer | Trainee checklists, today's assignments, Phase 4 form, route sort |
| Route Sort | driver | Per-driver route sort interface at the station |
| My Training | trainee | Training phase progress and task history |
| Anchor Points | driver | Staging area — arrive/depart lifecycle |
| Driver Survey | trainer, walker | End-of-shift survey form; read-only submitted view |
| Schedule | all field staff | Personal shift calendar |
| Schedule Changes | all | Submit schedule change requests; view status |
| Incidents | all field staff | Submit and track incident reports |
| Location Profiles | all | View and reference delivery location knowledge base |
| Preferences | driver, walker, trainer, trainee | Fav/ban management, assignment change requests |
| Notifications | all | In-app notification inbox with expiry-aware filtering |
| Account / Profile | all | Personal account details and sign-out |

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
│   ├── alembic/versions/        # 88 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_caller_employee, require_configured
│   │   ├── models/              # 39 SQLAlchemy models
│   │   ├── routers/             # 36 API routers under /api/v1/
│   │   │   └── internal.py      # Bot-facing endpoints (/internal/*), X-Internal-Secret auth
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic (proprietary algorithm files gitignored)
│   │   │   └── constants.py     # Role constants — single source of truth
│   │   └── tasks/               # Celery periodic tasks
│   ├── tests/                   # 236 pytest tests
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
│       └── pages/               # 34 route pages
├── mobile/
│   └── src/
│       ├── api/                 # apiClient (JWT interceptor, token refresh)
│       ├── contexts/            # AuthContext, ThemeContext
│       ├── navigation/          # RootNavigator, role-filtered horizontal tab bar
│       ├── screens/             # 16 screen directories (28 screen files)
│       └── theme/               # Shared design tokens (spacing, colors, typography)
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
- [x] **Phase 11** — Two-tier package routing: Tier 1 route sort (per-trainer sort sessions, sort commit, route sort screen), Tier 2 walker sub-route generation (anchor-point sort, location profiles, block-key tagging), graduation quiz gate, driver surveys
- [x] **Phase 12** — React Native mobile app: 16 screens across all field roles, role-filtered tab navigation, full feature parity with the web for field staff, notification inbox, gear requests, trainer role Discord sync
- [ ] **Phase 13** — Demo tenant + recorded walkthrough, E2E tests, staging environment, avatar image upload (S3), push notifications (Expo), offline-first optimistic updates

---

## Key Design Decisions

Architectural decisions are documented internally (130 ADRs). Key areas covered:

- Weighted dispatch algorithm design and fill-order logic
- Discord bot architecture and two-phase dispatch flow
- Multi-tenant data model and `company_id` isolation strategy
- Super admin panel and tenant provisioning flow
- Per-company Discord config with one bot serving multiple guilds
- `RoleChecker` vs `get_caller_employee` and the tenant isolation audit rule
- Two-tier package routing architecture and geographic clustering design
- Notification expiry model — time-scoped CTAs tied to dispatch date and survey day
- Graduation quiz gate — quiz-based promotion with paired trainer notification
- Driver survey lifecycle — activation guard, midnight close enforcement, response drill-down

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full system architecture.

---

## What's Left

- **Demo access** — demo tenant with seeded data and a recorded walkthrough for client presentations
- **E2E tests** — pytest covers backend services; no browser-level tests for the React frontend or mobile
- **Staging environment** — CI pipeline has a commented-out staging deploy job; no staging EC2 provisioned yet
- **Push notifications** — mobile notification inbox is in-app; Expo push token registration and background delivery not yet wired
- **Avatar upload** — S3 bucket for profile images is planned but not implemented

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
