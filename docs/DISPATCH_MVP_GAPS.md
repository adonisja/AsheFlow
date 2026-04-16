# AsheFlow Dispatch — MVP Gap Analysis
_Last updated: 2026-04-11 (Phase 5 role enforcement complete)_

This document tracks what is built, what is missing, and what the priority order is to reach a shippable MVP. It is updated as gaps are closed.

---

## Phase Summary

| Phase | Scope | Status |
|---|---|---|
| Phase 1 | Data models, dispatch algorithm, core routers | ✅ Complete |
| Phase 2 | Auth (Cognito), RBAC, Alembic migrations, API versioning, dispatch overrides | ✅ Complete |
| Phase 3 | Frontend infrastructure — Vite, Tailwind, auth context, base pages | ✅ Complete |
| Phase 4 | Field Ops (6 driver tools), training system, incidents, notifications, feedback, crew rebalancing | ✅ Complete |
| Phase 5 | Role architecture audit, dashboard split, reporting endpoints, tool scope enforcement, schedule change system | ✅ Complete |
| Phase 6 | Unit tests, Discord bot integration | ❌ Not started |

---

## What Is Fully Built (as of 2026-04-11)

### Core Dispatch System
| Component | Status |
|---|---|
| SQLAlchemy models: Employee, Truck, TruckAssignment, AssignmentMember, EmployeeRelationship, EmployeeOffDay | ✅ |
| Full employee/truck CRUD with management/admin gating | ✅ |
| Fav/ban relationship management (driver, walker, trainer only) | ✅ |
| Recurring off-day management (`employee_off_days`) | ✅ |
| PTO calendar requests (`time_off_requests`) | ✅ |
| Dispatch algorithm: available_pool → calculate_weights → assign_drivers → assign_trainers → assign_walkers | ✅ |
| Walker ban override with senior crew preference logic | ✅ |
| `POST /dispatch/` with duplicate guard and driver shortage handling | ✅ |
| `PATCH /dispatch/assign` manual assignment endpoint | ✅ |
| `DELETE` member removal and `PATCH` swap endpoints for post-dispatch edits | ✅ |
| Alembic migrations (17 total, full schema history) | ✅ |
| API versioning under `/api/v1/` | ✅ |
| AWS Cognito JWT validation via JWKS (`get_current_user`, `RoleChecker`) | ✅ |

### Field Ops (Driver Tools)
| Tool | Status |
|---|---|
| Check-In (`POST /field-ops/check-in`) — one per driver per day, timestamp displayed | ✅ |
| Departure (`POST /field-ops/departure`) — gated on check-in existing | ✅ |
| Return / End-of-Day (`POST /field-ops/return/{id}`) — stamps returned_at, shift duration computable | ✅ |
| Walker Attendance + Rating (`POST /field-ops/rating`) — present/no-show + 1–5 stars, crew validation | ✅ |
| Pre-Trip Vehicle Inspection (`POST /field-ops/inspection`) — 10-item checklist, failure detection | ✅ |
| Fuel / Mileage Log (`POST /field-ops/fuel-log`, `PATCH`) — start + end odometer, distance computed | ✅ |
| Crew lookup (`GET /field-ops/crew/{id}`) | ✅ |
| All Field Ops POST endpoints restricted to `driver` role only | ✅ |

### Training System
| Component | Status |
|---|---|
| Models: TrainingCurriculum, TrainingRecord, TrainingTask | ✅ |
| Curriculum injection hook in dispatch — rolls over training debt from prior days | ✅ |
| Trainee assignment service with trainer-centric placement | ✅ |
| Training debt age tracking and escalation | ✅ |
| Trainer continuation requests (request additional days with a specific trainee) | ✅ |
| Graduate trainees service (role change on completion) | ✅ |
| `/training/pipeline-summary` reporting endpoint | ✅ |
| TrainerDashboard page + TraineeDashboard page | ✅ |
| TraineeManagement page (management/admin) | ✅ |

### Incidents
| Component | Status |
|---|---|
| Incident model: category, severity, description, photo_url, driver_id, packages_tba, location, witness, medical | ✅ |
| `POST /incidents/` — all field staff can submit | ✅ |
| `GET /incidents/` — management/admin view all | ✅ |
| `GET /incidents/my` — own incidents | ✅ |
| `GET /incidents/unresolved-urgent` — dispatch/management/admin queue | ✅ |
| `PATCH /incidents/{id}/resolve` — management/admin/dispatch | ✅ |
| `GET /incidents/summary` — count by severity/category, management reporting | ✅ |

### Schedule Change Requests (new in Phase 5)
| Component | Status |
|---|---|
| `ScheduleChangeRequest` model with 3 modes: add_day, drop_day, full_rework | ✅ |
| `POST /schedule-change-requests/` — one-pending-at-a-time guard, notifies management/admin | ✅ |
| `PATCH /{id}/approve` — auto-applies mutation to `employee_off_days` | ✅ |
| `PATCH /{id}/reject` — notifies employee | ✅ |
| `DELETE /{id}` — self-cancel pending | ✅ |
| `/schedule-changes` frontend page — 3-mode form, current schedule display, reviewer panel | ✅ |

### Assignment Change Requests (Truck Reassignment)
| Component | Status |
|---|---|
| `AssignmentChangeRequest` model | ✅ |
| `POST /` — walker/trainer only, today-only, active assignment required, ownership enforced | ✅ |
| `GET /pending` — dispatch/admin queue | ✅ |
| Approve/reject endpoints with employee notifications | ✅ |
| Today-only form in Preferences (no date picker — always submits today) | ✅ |

### Dashboard & Role Architecture
| Component | Status |
|---|---|
| `DispatchView` — pending approvals (reassignment, time-off, off-days), active incidents, fleet return | ✅ |
| `ManagementView` — KPIs, incident trends, walker performance, training pipeline, vehicle compliance | ✅ |
| `WorkerView` — role-aware quick links for field staff | ✅ |
| Admin 3-tab switcher (dispatch / management / worker perspective) | ✅ |
| `AdminDashboard` at `/admin` — workforce breakdown, open incidents resolve, training sessions, employee roster, fleet grid | ✅ |
| All backend routers authenticated (no open endpoints) | ✅ |
| Role-specific navbar visibility (dispatch, field staff, management, admin all see different links) | ✅ |

### Reporting Endpoints (management)
| Endpoint | Status |
|---|---|
| `GET /field-ops/no-shows` — walker no-shows for a date | ✅ |
| `GET /field-ops/walker-stats` — avg stars + no-show rate per walker, rolling week | ✅ |
| `GET /field-ops/inspection-failures/summary` — failure counts per item | ✅ |
| `GET /field-ops/returns/summary` — shift durations and return status | ✅ |
| `GET /incidents/summary` — counts by severity/category over N days | ✅ |
| `GET /training/pipeline-summary` — active trainees, sessions today, trainer loads | ✅ |

---

## Remaining Gaps

### P1 — Quality Gate

**Unit tests for dispatch services**
- No test files exist for the dispatch service layer.
- Coverage needed:
  - `calculate_weights` — fan boost, consecutive penalty, cap enforcement
  - `assign_drivers` — one driver per truck, no repeats
  - `assign_trainers` — ban exclusion, two-pass spread, warning on all-zero
  - `assign_walkers` — ban override, hard ban, spread cap
  - `run_dispatch` — driver shortage raises ValueError, full pipeline produces correct output shape
- Framework: pytest + SQLAlchemy in-memory (SQLite) or test fixtures
- **Status:** ❌ Not built

---

### P2 — Operational Completeness

**Discord Bot**
- The Discord server is the team's primary communication channel. The bot will be a thin client over the REST API — all business logic stays in the backend.
- Previously blocked on auth, manual assignment endpoint, and API versioning — all three are now complete.
- Planned commands:

| Command | Endpoint | Required Role |
|---|---|---|
| `!dispatch run` | `POST /api/v1/dispatch/` | dispatch |
| `!dispatch status <date>` | `GET /api/v1/dispatch/<date>` | all |
| `!assign <employee> <truck> <role>` | `POST /api/v1/dispatch/assign` | dispatch |
| `!dayoff request <date>` | `POST /api/v1/time-off-requests/` | field staff |
| `!dayoff approve <id>` | `PATCH /api/v1/time-off-requests/{id}/approve` | management, admin |
| `!fav add <employee>` | `POST /api/v1/employee-relationships/` | driver, walker, trainer |
| `!ban add <employee>` | `POST /api/v1/employee-relationships/` | driver, walker, trainer |
| `!crew <date>` | `GET /api/v1/schedule/{employee_id}` | all |

- **Status:** ❌ Not started

---

### P3 — Future / Nice to Have

| Item | Notes |
|---|---|
| Photo storage via S3 / presigned URLs | Check-in, departure, and incident photos currently stored as base64 in DB — will bloat |
| Late check-in flag relative to scheduled dispatch time | Low priority UX enhancement |
| Rating window enforcement (submit at end of shift) | Currently open all day |
| Walker aggregate rating UI visible to management | `GET /field-ops/rating/walker/{id}` endpoint exists; no management UI surface yet |
| `assignment_change_requests` retention policy | Old resolved rows accumulate with no automatic cleanup |
| Schedule view for dispatch employees | Dispatch employees have a schedule but it doesn't appear in the schedule tool |

---

## Summary Status Table

| # | Item | Status |
|---|---|---|
| 1 | Fix circular import | ✅ |
| 2 | Fix legacy router imports | ✅ |
| 3 | Authentication + JWT (Cognito) | ✅ |
| 4 | RBAC on all endpoints | ✅ |
| 5 | Manual assignment endpoint | ✅ |
| 6 | Dispatch override/edit after run | ✅ |
| 7 | Alembic migrations | ✅ |
| 8 | API versioning | ✅ |
| 9 | Field Ops — 6 driver tools | ✅ |
| 10 | Training system — curriculum, injection, debt, continuation | ✅ |
| 11 | Incidents system | ✅ |
| 12 | Notifications system | ✅ |
| 13 | Crew rebalancing post-assignment | ✅ |
| 14 | Role architecture audit + dashboard split | ✅ |
| 15 | 6 management reporting endpoints | ✅ |
| 16 | Schedule Change Request (3-mode, auto-apply) | ✅ |
| 17 | Truck Reassignment (today-only, assignment guard) | ✅ |
| 18 | All previously unauthenticated routers secured | ✅ |
| 19 | Tool scope enforcement (fav/ban, field-ops, role nav) | ✅ |
| 20 | Unit tests — dispatch service layer | ❌ |
| 21 | Discord bot | ❌ |
| 22 | S3 photo storage | ❌ (future) |
