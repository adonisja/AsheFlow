# AsheFlow — Crew Management & Dispatch Platform

A full-stack B2B platform for delivery crew management, intelligent dispatching, field operations, and workforce analytics. Built with FastAPI, PostgreSQL, and React.

---

## What It Does

AsheFlow replaces manual scheduling spreadsheets and verbal coordination with a structured, role-aware system that covers the full shift lifecycle — from dispatch planning in the morning to walker ratings and fuel logs at the end of the day.

**Core capabilities:**
- **Intelligent Dispatch** — weighted algorithm that resolves driver preferences (favorites/bans), recurring off-days, trainer-trainee pairing, and crew balance constraints to generate daily truck assignments
- **Field Operations** — driver shift lifecycle: check-in, pre-trip inspection, departure, walker attendance + rating, fuel/mileage log, end-of-day return
- **Training Pipeline** — 5-day trainee onboarding with curriculum injection, training debt escalation, trainer continuation requests, and automated graduation
- **Incident Reporting** — structured mid-shift reports with severity tags, auto-notification to management, and resolution tracking
- **Schedule Management** — PTO calendar requests, recurring off-day management, and a 3-mode schedule change request system (add days, drop days, or full rework)
- **Role-Scoped Dashboards** — each role sees a different interface: dispatch gets operational tools, management gets reporting panels, workers get a personal overview, admin gets a system control panel

---

## Role Definitions

| Role | Who | Access |
|---|---|---|
| `driver` | Vehicle operators | Field Ops, Schedule, Preferences (fav/ban, reassignment), Schedule Changes, Incidents |
| `walker` | Package delivery on foot | Schedule, Preferences (fav/ban, reassignment), Schedule Changes, Incidents |
| `trainer` | Senior staff training new hires | Schedule, Preferences (fav/ban, reassignment), Schedule Changes, Trainer Dashboard, Incidents |
| `trainee` | New hires in training program | Schedule, My Training, Schedule Changes, Incidents |
| `dispatch` | Scheduling coordinator | Dispatch Center, Schedule Changes, Incidents, Dashboard (operational view) |
| `management` | Operations supervisor | Reporting dashboard, approval queues (time-off, off-days, schedule changes), Incidents, Trainees |
| `admin` | Tech lead / developer | Everything — system tools, all dashboards, full override access |

---

## Architecture

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL (Docker container)
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic (17 migrations)
- **Auth:** AWS Cognito (JWT verification via JWKS, `RoleChecker` dependency)

### Frontend
- **Framework:** React 18 + TypeScript (Vite)
- **Styling:** Tailwind CSS with custom design tokens
- **Auth:** AWS Amplify + Cognito Federated Identity (Discord SSO)
- **API Client:** Axios with JWT interceptor

### Infrastructure
- **Containerization:** Docker + Docker Compose
- **Seed data:** `backend/seed.py` for populated dev environments

---

## Project Structure

```
AsheFlow/
├── backend/
│   ├── alembic/versions/        # 17 database migrations
│   ├── app/
│   │   ├── api/deps.py          # RoleChecker, get_current_user, get_caller_employee
│   │   ├── models/              # SQLAlchemy models (16 tables)
│   │   ├── routers/             # 16 API routers under /api/v1/
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── services/            # Dispatch algorithm + business logic
│   ├── seed.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                 # Axios bindings
│       ├── components/
│       │   ├── auth/            # Login
│       │   ├── dashboard/       # DispatchView, ManagementView, WorkerView
│       │   └── layout/          # Navbar, Layout
│       ├── contexts/            # AuthContext
│       └── pages/               # 11 route pages
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

All endpoints live under `/api/v1/`. Authentication is required on every endpoint via AWS Cognito JWT Bearer token.

| Router | Endpoints | Access |
|---|---|---|
| `/employees` | CRUD | management, admin |
| `/trucks` | CRUD | management, admin |
| `/dispatch` | Run, assign, swap, clear | dispatch, admin |
| `/schedule` | View by employee, available by date | authenticated |
| `/employee-off-days` | CRUD + approve | field staff (submit), management (approve) |
| `/time-off-requests` | CRUD + approve | field staff (submit), management (approve) |
| `/schedule-change-requests` | Submit, approve, reject, cancel | field staff + dispatch (submit), management + admin (review) |
| `/assignment-change-requests` | Submit, approve, reject, cancel | walker + trainer (submit), dispatch (review) |
| `/employee-relationships` | Fav/ban CRUD | driver, walker, trainer |
| `/field-ops` | Check-in, departure, return, inspection, rating, fuel log | driver (submit), management (read) |
| `/incidents` | Submit, resolve, summary | all field staff (submit), management (manage) |
| `/training` | Curriculum, records, tasks, pipeline summary | trainer, trainee, management |
| `/notifications` | Read, mark read, clear | authenticated |
| `/feedback` | Submit | field staff |

---

## Development Roadmap

- [x] **Phase 1** — Data models, dispatch algorithm, core CRUD routers
- [x] **Phase 2** — AWS Cognito auth, RBAC (`RoleChecker`), Alembic migrations, API versioning, dispatch overrides
- [x] **Phase 3** — Frontend: Vite + Tailwind, auth context, base pages (Schedule, Preferences, Dashboard)
- [x] **Phase 4** — Field Ops (6 driver tools), training pipeline, incidents, crew rebalancing, notifications
- [x] **Phase 5** — Role architecture audit, dashboard split (Dispatch/Management/Worker/Admin), 6 reporting endpoints, schedule change request system, tool scope enforcement
- [ ] **Phase 6** — Unit tests (dispatch service layer), Discord bot integration

---

## What's Left

Two items remain before the system is considered MVP-complete:

1. **Unit tests** — the dispatch algorithm service layer (calculate_weights, assign_drivers, assign_trainers, assign_walkers, run_dispatch) has no automated test coverage
2. **Discord bot** — thin REST client over the existing API for in-Discord dispatch commands and crew lookup; all blockers (auth, manual assignment, API versioning) are resolved
