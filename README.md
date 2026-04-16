# AsheFlow — Crew Management & Dispatch Platform

A full-stack B2B platform for delivery crew management, intelligent dispatching, field operations, and workforce analytics. Built with FastAPI, PostgreSQL, and React.

---

## What It Does

AsheFlow replaces manual scheduling spreadsheets and verbal coordination with a structured, role-aware system that covers the full shift lifecycle — from dispatch planning in the morning to walker ratings and fuel logs at the end of the day.

**Core capabilities:**
- **Intelligent Dispatch** — weighted algorithm that resolves driver preferences (favorites/bans), recurring off-days, PTO requests, trainer-trainee pairing, and crew balance constraints to generate daily truck assignments
- **Field Operations** — driver shift lifecycle: check-in, pre-trip inspection, departure, walker attendance + rating, fuel/mileage log, end-of-day return
- **Training Pipeline** — 5-day trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, and automated graduation
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system (add days, drop days, or full rework)
- **Workforce Analytics** — walker performance leaderboard with letter grades, driver bias detection, vehicle compliance trending, and availability heatmaps
- **Role-Scoped Dashboards** — each role lands on a purpose-built home page; no generic fallback for roles with dedicated tools

---

## Role Definitions

| Role | Who | Home Page | Key Access |
|---|---|---|---|
| `driver` | Vehicle operators | Management Dashboard | Field Ops, Schedule, Preferences, Schedule Changes, Incidents |
| `walker` | Package delivery on foot | Management Dashboard | Schedule, Preferences, Schedule Changes, Incidents |
| `trainer` | Senior staff training new hires | Trainer Dashboard | Schedule, Preferences, Schedule Changes, Trainer Dashboard, Incidents |
| `trainee` | New hires in training program | My Training | Schedule, My Training, Schedule Changes, Incidents |
| `dispatch` | Scheduling coordinator | Dispatch Center | Dispatch Center, Schedule Changes, Incidents |
| `management` | Operations supervisor | Management Dashboard | Reporting dashboard, approval queues (PTO, off-days, schedule changes, assignment changes), Incidents, Trainee Management, Walker Performance, Vehicle Compliance |
| `admin` | Tech lead / developer | Admin Dashboard | Everything — all dashboards, system tools, feedback inbox, full override access |

---

## Architecture

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL (Docker container)
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic (27 migrations)
- **Auth:** AWS Cognito (JWT verification via JWKS with key-rotation retry, `RoleChecker` dependency injection)
- **Tests:** pytest — 5 dispatch service modules covered (assign_trainees, assign_trainers, assign_walkers, calculate_weights, run_dispatch)

### Frontend
- **Framework:** React 18 + TypeScript (Vite)
- **Styling:** Tailwind CSS with custom design tokens
- **Auth:** AWS Amplify + Cognito Federated Identity (Discord SSO)
- **API Client:** Axios with JWT interceptor (`axiosClient` — the only permitted import for API calls)

### Infrastructure
- **Containerization:** Docker + Docker Compose
- **Seed data:** `backend/seed.py` for populated dev environments

---

## Project Structure

```
AsheFlow/
├── backend/
│   ├── alembic/versions/        # 27 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_current_user, get_caller_employee
│   │   ├── models/              # SQLAlchemy models (16 tables)
│   │   ├── routers/             # 16 API routers under /api/v1/
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── services/            # Dispatch algorithm + business logic
│   ├── tests/                   # pytest — dispatch service layer
│   ├── seed.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                 # axiosClient (JWT interceptor)
│       ├── components/
│       │   ├── auth/            # Login
│       │   ├── dashboard/       # ManagementView
│       │   └── layout/          # Navbar, Layout
│       ├── contexts/            # AuthContext
│       └── pages/               # 15 route pages
├── docs/
│   ├── decisions/               # ADRs (ADR-001 through ADR-038)
│   ├── journals/                # Per-session development logs
│   ├── LEARNING_GUIDE.md        # Accumulated design lessons
│   └── ARCHITECTURE.md
└── docker-compose.yml
```

---

## Development Setup

### Prerequisites
- Docker & Docker Compose
- AWS Cognito User Pool with a configured App Client

### Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/adonisja/AsheFlow.git
   cd AsheFlow
   ```

2. **Set environment variables**
   - `backend/.env` — see `backend/.env.example`
   - `frontend/.env` — see `frontend/.env.template`
   - Both need `AWS_COGNITO_USER_POOL_ID` and `AWS_REGION`

3. **Start the stack**
   ```bash
   docker-compose up --build
   ```

4. **Run migrations and seed data**
   ```bash
   docker exec -it asheflow_backend alembic upgrade head
   docker exec -it asheflow_backend python seed.py
   ```

**Available at:**
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

---

## API Surface

All endpoints live under `/api/v1/`. Authentication is required on every endpoint via AWS Cognito JWT Bearer token. Ownership checks are enforced on all personal-data write endpoints.

| Router | Endpoints | Access |
|---|---|---|
| `/employees` | CRUD, deactivate, `/me` | management, admin (write); authenticated (read own) |
| `/trucks` | CRUD, deactivate | management, admin |
| `/dispatch` | Run, assign, swap, clear, unavailable staff | dispatch, admin |
| `/schedule` | View by employee, available by date, availability summary | authenticated |
| `/employee-off-days` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/time-off-requests` | CRUD + approve | field staff (submit); management, admin (approve) |
| `/schedule-change-requests` | Submit, approve, reject, cancel | field staff, dispatch (submit); management, admin (review) |
| `/assignment-change-requests` | Submit, approve, reject, cancel | walker, trainer (submit); dispatch (review) |
| `/employee-relationships` | Fav/ban CRUD | driver, walker, trainer (own records only); dispatch, management, admin (read) |
| `/field-ops` | Check-in, departure, return, inspection, rating, fuel log | driver (submit); management, admin (read) |
| `/incidents` | Submit, resolve, summary | all field staff (submit); management, admin (manage) |
| `/training` | Curriculum, records, tasks, pipeline summary | trainer, trainee, management, admin |
| `/notifications` | Read, mark read, clear | authenticated (own only) |
| `/feedback` | Submit, list, update status | authenticated (submit); admin (list, update) |

---

## Pages

| Route | Roles | Purpose |
|---|---|---|
| `/` | all | Role-aware redirect to home page |
| `/dispatch` | dispatch, admin | Run dispatch, drag-and-drop crew assignment, call-in list |
| `/schedule` | all field staff, management, admin | Personal calendar + PTO (field staff); approval queue + heatmap (management/admin) |
| `/field-ops` | driver, admin | Driver shift tools (driver); field activity analytics (admin) |
| `/incidents` | all field staff, dispatch, management, admin | Submit incidents; management resolve queue |
| `/preferences` | driver, walker, trainer, admin | Fav/ban manager, assignment change requests (field staff); system-wide analytics (admin) |
| `/schedule-changes` | all field staff, dispatch, admin | Submit schedule change requests (field staff/dispatch); analytics + approval queue (admin) |
| `/trainer-dashboard` | trainer, admin | Trainee task checklists, continuation request management |
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
- [x] **Phase 6** — Analytics pages (Walker Performance, Vehicle Compliance, Admin Field Ops, Admin Preferences), security audit (ownership checks, schema validation, JWKS rotation, credential hygiene), dispatch unit tests, feedback admin UI, bug fixes (PTO dispatch filter, drag-and-drop role assignment)
- [ ] **Phase 7** — Discord bot integration, TruckAssignment lifecycle automation, dispatch confirmation system

---

## What's Left

Three items are the highest priority before the system is considered MVP-complete:

1. **Discord bot** — thin REST client over the existing API for in-Discord dispatch confirmation and crew lookup; all API blockers are resolved
2. **TruckAssignment lifecycle** — hook the existing `status` field (`planned → active → completed`) into departure and return events so the management dashboard can show real-time fleet status
3. **Dispatch confirmation system** — model a `DispatchConfirmation` table so dispatched employees can confirm or decline assignments before the window closes
