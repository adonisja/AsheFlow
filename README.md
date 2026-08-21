<p align="center">
  <img src="frontend/src/assets/logo-full.svg" alt="AsheFlow Logo" width="280" />
</p>

<p align="center">
  <strong>Crew Management & Intelligent Dispatch for Amazon DSP Operations</strong><br/>
  <sub>Multi-tenant · Role-scoped · Discord-integrated · Mobile-first · Deployed on AWS</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/build-passing-brightgreen?style=flat-square" alt="Build" />
  <img src="https://img.shields.io/badge/tests-582%20passing-brightgreen?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/react_native-0.85-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React Native" />
  <img src="https://img.shields.io/badge/license-BSL%201.1-orange?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/status-deployed%20(staging)-success?style=flat-square" alt="Status" />
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

- **Intelligent Dispatch** — weighted algorithm resolving driver preferences (favorites/bans), recurring off-days, PTO, trainer-trainee pairing, consecutive-assignment penalties, and crew balance to generate daily truck assignments; per-truck selection and re-run
- **Two-Phase Discord Flow** — crew DM confirmations after dispatch; a second "Post Final Crews" action publishes finalized assignments to per-truck Discord channels, gated on a per-truck confirmation-rate check (blocks a near-empty crew from being posted)
- **Dispatch Confirmation System** — tracks each crew member's response (confirmed/declined/pending) with timestamps; trainer declines trigger automatic trainee reassignment; SSE + stop-conditioned polling keep the dispatch board live without hammering the API
- **Full Driver Day** — an end-to-end field-ops wizard covering the whole shift: confirm assignment → check-in → pre-trip → starting odometer → station arrival → gate/dock assignment → load truck (tote check-off + load confirmation) → depart → **anchor point + geocoded ETA** → on-route check-ins → RTS/return-to-station report → station handoff → end-of-day odometer + inspection → sign-out
- **Anchor Points** — the driver posts a preliminary staging point (cross-street/address geocoded via NYC GeoClient) with a mandatory ETA; crew see the meet-up point, arrival status, relocations, and running-late alerts (timezone-correct); a crew-facing "Today's Assignment" view mirrors it for trainers/walkers/trainees
- **Shared Roll-Call** — one presence source per crew member per day, read and written by trainers, the driver's check-in, and dispatch alike (field-staff latest-wins; a dispatch override locks the record)
- **Two-Tier Package Routing** — Tier 1 route sort at the station (tote-level anchor assignment, equity by tote count, commit-to-routes); Tier 2 walker sub-route generation at the anchor point (banded-urgency wave distribution, fairness-weighted per-walker route cards, misroute detection + one-tap resolve, mid-day freight best-fit)
- **Training Pipeline** — phase-based trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, trainer marks, Phase 4 observation forms, late-trainee join handling, and a graduation quiz gate
- **ADP Payroll Integration** — employee import from ADP RUN, daily timecard reconciliation against shift records, and a mismatch-resolution workflow
- **Amazon Scorecards** — upload the weekly DSP scorecard (individual + company), auto-extract metrics via AWS Textract, and cross-check contestable figures (packages delivered, completion DPMO) against our own delivery/RTS data
- **Location Profiles** — two-tier location knowledge base: company-managed profiles with a global library for promotion; cold-start bulk creation; block-key-based routing integration
- **Driver Surveys** — end-of-shift feedback from trainers and walkers; management activates per-day, yes/no questions + notes, visual results with per-question % bars and individual drill-down
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system
- **Gear Requests** — field staff request equipment; management review and fulfilment tracking
- **Workforce Analytics** — dispatch fill rate, trainer load, ban override frequency, confirmation response times, walker performance leaderboard, driver bias detection, vehicle compliance trending, availability heatmaps
- **Role-Scoped Dashboards** — each of 8 roles lands on a purpose-built home page with self-view analytics panels
- **Notification Inbox** — in-app notifications with expiry; typed notifications across every workflow; Discord DM mirroring for time-sensitive alerts
- **Design System + Theming** — a shared token/primitive library across web and mobile, full light/dark support with an in-app toggle, and accessibility baked in (WCAG tap targets, contrast)
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
| Backend API | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Uvicorn · SSE (StreamingResponse) |
| Database | PostgreSQL 15 · Alembic (136 migrations) · Redis 7 |
| Async / jobs | Celery worker + beat (periodic alerts, reconciliation) |
| Auth | AWS Cognito (JWKS, short-TTL JWTs, revocation) |
| Web Frontend | React 19 · TypeScript · Vite · Tailwind CSS 3 · Axios |
| Mobile App | React Native 0.85 (bare, iOS + Android) · TypeScript · React Navigation |
| Bot | discord.py · Cognito service account · per-guild routing |
| Integrations | NYC GeoClient (geocoding) · AWS Textract (scorecard OCR) · ADP RUN (payroll) |
| Infrastructure | Docker Compose · AWS EC2 · AWS SSM deploy · GitHub Actions CI/CD |
| Tests | pytest · 582 tests · SQLite in-memory + mock-DB fixtures |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                            │
│  Browser (React 19 + Tailwind)  │  Mobile (React Native 0.85) │
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
│    /api/v1/ · 41 routers │  │    X-Internal-Secret     │
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
- React Native toolchain for the mobile app: Xcode + CocoaPods (iOS) and/or Android Studio + an AVD (Android) — this is a **bare React Native** app, not Expo

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

**5. Start the mobile app** (bare React Native)
```bash
cd mobile && npm install
cd ios && pod install && cd ..   # iOS only
npm run ios       # or: npm run android
```

**6. Run tests**
```bash
docker exec -it asheflow_backend python -m pytest tests/ -v
```

**Available at:**
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Mobile: iOS Simulator / Android emulator via the Metro bundler

</details>

<details>
<summary><strong>Environment Variables Reference</strong></summary>

| File | Key Variables |
|---|---|
| `.env` (root) | `POSTGRES_PASSWORD`, `SECRET_KEY` |
| `backend/.env` | `DATABASE_URL`, `REDIS_URL`, `AWS_COGNITO_USER_POOL_ID`, `AWS_COGNITO_APP_CLIENT_ID`, `INTERNAL_SECRET` |
| `frontend/.env` | `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_APP_CLIENT_ID`, `VITE_API_BASE_URL` |
| `mobile/.env` | `ASHEFLOW_API_URL` (override; falls back to `ASHEFLOW_LAN_IP` for local), Cognito pool/client IDs — inlined at build time via `react-native-dotenv` |
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
<summary><strong>View all 41 routers</strong></summary>

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
| `/field-ops` | Check-in, departure, return, inspection, rating, fuel log, walker profile, performance | driver (submit); walker (own profile); management, admin (read) |
| `/shift-sessions` | Active session state, heartbeat | driver, management, admin |
| `/shift-ops` | Mid-shift check-ins, crew compliance, RTS report review, station handoff | driver (submit); dispatch, management, admin |
| `/roll-call` | Shared crew presence — submit/upsert, my-truck, summary, confirm | driver, trainer (own truck); dispatch, management, admin |
| `/crew-status` | Derived per-truck crew availability (presence + route progress) | driver, trainer, dispatch, management, admin |
| `/rts` | Return-to-station packages, missing/damaged, route handoff | driver, trainer (submit); management, admin |
| `/anchor-points` | Preliminary AP + geocoded ETA, arrive/relocate/depart lifecycle, late flags | driver (own truck); all field roles (read); dispatch, management, admin |
| `/walker-routes` | Tier-2 wave distribution, AP arrival, route stops, rebalance | driver, trainer; dispatch, management, admin |
| `/scorecards` | Weekly Amazon scorecard upload, Textract parse, cross-check | management, admin |
| `/adp` | ADP RUN employee import, timecard reconciliation, mismatch resolution | management, admin |
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
<summary><strong>View all 36 routes</strong></summary>

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
| `/scorecard-entry` | management, admin | Upload the weekly Amazon scorecard, auto-extract via Textract, cross-check contestable metrics |
| `/crew-status` | driver, trainer, dispatch, management, admin | Live per-truck crew presence + route-progress availability |
| `/notifications-history` | authenticated | Full notification history with type filtering |
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

The mobile app targets field staff — drivers, walkers, trainers, and trainees. Built with bare React Native 0.85 (iOS + Android), it uses a horizontal scrollable tab bar that renders only the tabs relevant to the authenticated user's role, with a shared design-system + light/dark theming matching the web.

<details>
<summary><strong>View all mobile screens</strong></summary>

| Screen | Roles | Purpose |
|---|---|---|
| Home | all | Today's assignment summary, quick-nav to key tools |
| Today's Assignment | all | Full assignment detail for the current day |
| Field Ops | driver, walker, trainer, trainee | Full driver-day wizard (paged, section-themed, progress bar) — check-in, inspection, odometer, load, anchor point, on-route check-ins, RTS report, handoff, EOD; walker performance view |
| Walker Dashboard | walker | Own performance metrics, rating history |
| Training | trainer, trainee | Trainee checklists, today's session, Phase 4 form, marks, performance (tab title tracks the active section) |
| Route Sort | driver, trainer | Tier-1/Tier-2 sort at the station/AP; crew roster with roll-call marking |
| My Route | trainer, trainee | Assigned route stops and progress |
| Anchor Point | driver, trainer, trainee, walker | Role-branched: driver posts/relocates the AP + confirms arrival; crew see the meet-up point, ETA and arrival status |
| Reattempts | driver, trainer | Failed-delivery reattempt assignment and outcome tracking |
| Driver Survey | trainer, walker | End-of-shift survey form; read-only submitted view |
| Schedule | all field staff | Personal shift calendar + PTO; "Schedule Changes" sub-tab for change requests |
| Change Requests | dispatch, management, admin | Reviewer queue for schedule-change requests |
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
│   ├── alembic/versions/        # 136 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_caller_employee, require_configured
│   │   ├── models/              # 49 SQLAlchemy models
│   │   ├── routers/             # 41 API routers under /api/v1/
│   │   │   └── internal.py      # Bot-facing endpoints (/internal/*), X-Internal-Secret auth
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic (proprietary algorithm files gitignored)
│   │   │   └── constants.py     # Role constants — single source of truth
│   │   └── tasks/               # Celery periodic tasks
│   ├── tests/                   # 582 pytest tests
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
│       └── pages/               # 36 route pages
├── mobile/
│   └── src/
│       ├── api/                 # apiClient (JWT interceptor, token refresh)
│       ├── contexts/            # AuthContext, ThemeContext
│       ├── components/ui/       # Shared primitives (Button, Badge, Card, PageHeader, ThemeToggle)
│       ├── navigation/          # RootNavigator, role-filtered horizontal tab bar
│       ├── screens/             # 16 screen directories (31 screen files)
│       └── theme/               # Shared design tokens (spacing, color, type, light/dark)
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
- [x] **Phase 12** — React Native mobile app (bare): 16 screen areas across all field roles, role-filtered tab navigation, feature parity with the web for field staff, notification inbox, gear requests, trainer role Discord sync
- [x] **Phase 13** — Full driver day: mid-shift check-ins, RTS/return-to-station report, station handoff, dock/gate assignment + tote check-off + load confirmation, end-of-day flow; staging environment on EC2 + SSM/CI deploy
- [x] **Phase 14** — Anchor-point rework (geocoded ETA, relocation, running-late), shared bidirectional roll-call + crew status, timing/wave-distribution rebalance, arrival-model consolidation
- [x] **Phase 15** — Integrations + polish: ADP payroll import & timecard reconciliation, Amazon scorecard OCR + cross-check, SSE real-time, and a full web+mobile design-system re-adoption (theming, accessibility, header/UX unification)
- [ ] **Phase 16** — Demo tenant + recorded walkthrough, E2E tests (browser + mobile), push notifications, avatar upload (S3), offline-first optimistic updates

---

## Key Design Decisions

Architectural decisions are documented internally (210 ADRs). Key areas covered:

- Weighted dispatch algorithm design and fill-order logic
- Discord bot architecture and two-phase dispatch flow
- Multi-tenant data model and `company_id` isolation strategy
- Super admin panel and tenant provisioning flow
- Per-company Discord config with one bot serving multiple guilds
- `RoleChecker` vs `get_caller_employee` and the tenant isolation audit rule
- Two-tier package routing — tote-level station sort + banded-urgency walker wave distribution
- Notification expiry model — time-scoped CTAs tied to dispatch date and survey day
- Graduation quiz gate — quiz-based promotion with paired trainer notification
- Driver survey lifecycle — activation guard, midnight close enforcement, response drill-down
- Shared roll-call model — one presence row per crew member per day; field-staff latest-wins, dispatch lock
- Anchor-point geocoding — cross-street/address → GeoClient point; mandatory, timezone-correct ETA + late detection
- Real-time without polling storms — SSE for terminal dispatch state, stop-conditioned/visibility-gated polls elsewhere
- Design-system re-adoption — shared token/primitive layer, light/dark restored across web + mobile, no hardcoded colors

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full system architecture.

---

## What's Left

- **Demo access** — demo tenant with seeded data and a recorded walkthrough for client presentations
- **E2E tests** — pytest covers backend routers/services (582 tests); no browser-level tests for the React frontend or mobile yet
- **Push notifications** — the mobile notification inbox is in-app; native push token registration and background delivery are not yet wired
- **Avatar upload** — S3 bucket for profile images is planned but not implemented
- **Offline-first** — optimistic updates / offline queueing for the mobile field flow

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
