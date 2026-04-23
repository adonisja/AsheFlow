# AsheFlow — Capability Inventory
**Last updated:** 2026-04-18  
**Purpose:** Honest accounting of what is built, what is partial, what is missing, and what is implied but unstated. Use this before making any claims in external-facing documents.

---

## How to Read This Document

| Symbol | Meaning |
|--------|---------|
| ✅ Complete | Feature is built, tested, and in production use |
| ⚠️ Partial | Core logic exists but has known gaps or missing pieces |
| ❌ Missing | Not started — no backend, no frontend, no schema |
| 💡 Implied | Logically follows from what exists but has not been scoped or built |

---

## 1. Dispatch Algorithm

| Capability | Status | Notes |
|------------|--------|-------|
| Availability filtering (recurring off-days) | ✅ Complete | `available_pool.py` filters `EmployeeOffDay` |
| Availability filtering (approved PTO) | ✅ Complete | `available_pool.py` filters `TimeOffRequest` where `status = 'approved'` |
| Driver / Trainer / Walker / Trainee assignment | ✅ Complete | Four separate assignment services with multi-pass logic |
| Consecutive assignment penalty | ✅ Complete | `previous_assignment.py` applies 0.05× weight penalty |
| Ban list enforcement | ✅ Complete | `check_ban.py` + `ban_override.py` |
| Fan boost prioritization | ✅ Complete | Bidirectional and tridirectional mutual preference resolution |
| Training debt escalation | ✅ Complete | Trainees with unmet training days are prioritized |
| Crew rebalancing fallback | ✅ Complete | `rebalance_crews.py` fires when initial pass fails |
| Trainee graduation (auto-promotion after 5 assignments) | ✅ Complete | `graduate_trainees.py` |
| Dispatcher review before publish | ✅ Complete | No assignment is sent until dispatcher manually publishes |
| Preference weight configuration (admin-tunable) | ❌ Missing | `ROLE_BOOST` and `MUTUAL_BONUS` constants are hardcoded in `constants.py`; no UI or config surface to adjust them |
| Automated dispatch scheduling (run at configured time daily) | ❌ Missing | Celery Beat is active but no `dispatch_config` table or cron task wired for auto-run |

---

## 2. Discord Confirmation Workflow

| Capability | Status | Notes |
|------------|--------|-------|
| Discord DM to each crew member on publish | ✅ Complete | `bot/cogs/dispatch.py` handles DM delivery |
| Confirm / Decline buttons in DM | ✅ Complete | Persistent button views with state |
| Driver confirmation deadline (8:20 AM) enforcement | ⚠️ Partial | `CONFIRMATION_WINDOW_HOURS` config exists; Celery Beat is live — but no task is wired to fire at 8:20 AM to flag unconfirmed drivers |
| Crew confirmation deadline (9:00 AM) enforcement | ⚠️ Partial | Same gap as above — deadline exists conceptually but no automated enforcement task |
| Decline alert to dispatcher | ✅ Complete | Bot posts to `#drivers-chat` on any decline |
| `no_show` status (deadline passed, no response) | ❌ Missing | `DispatchConfirmation.status` only has `pending / confirmed / declined` |
| Official crew post to truck channels at 9:05 AM | ❌ Missing | No scheduled task wired to post finalized roster to per-truck channels |
| Master crew list post to Drivers' Chat at 9:05 AM | ❌ Missing | Same gap |

---

## 3. Real-Time Operations Dashboard

| Capability | Status | Notes |
|------------|--------|-------|
| Fleet status board | ⚠️ Partial | `TruckAssignment.status` column exists (`planned / active / completed`) but **never mutates** — always stays `planned`. Fleet board queries can't use it meaningfully |
| Live confirmation tracker (confirmed / pending / declined per truck) | ✅ Complete | `GET /dispatch/{date}/confirmations` endpoint exists; frontend renders counts |
| Staff availability panel (who is off and why) | ✅ Complete | `GET /dispatch/unavailable-staff/{date}` returns off-day and PTO entries |
| Pending change requests view | ✅ Complete | Schedule change and assignment change request endpoints with approval workflow |
| Real-time push / WebSocket | ❌ Missing | All data is REST/polling; no WebSocket connections; data refreshes only on manual user action |

---

## 4. Field Operations Tracking

| Capability | Status | Notes |
|------------|--------|-------|
| Check-in (driver arrival on site) | ✅ Complete | `CheckIn` model + endpoint |
| Pre-trip vehicle inspection (structured checklist) | ✅ Complete | `VehicleInspection` model with JSONB checklist items and `has_failures` flag |
| Inspection failure alert to dispatcher | ❌ Missing | `has_failures` is stored but no notification is fired on submission |
| Departure recording (`departed_at` timestamp) | ✅ Complete | `Departure.departed_at` |
| Return recording (`returned_at` timestamp) | ✅ Complete | `Departure.returned_at` |
| `TruckAssignment.status` → `active` on departure | ❌ Missing | Transition never wired — status stays `planned` |
| `TruckAssignment.status` → `completed` on return | ❌ Missing | Transition never wired |
| Walker attendance and ratings | ✅ Complete | `WalkerRating` model with `present`, `stars`, `comment` |
| Rating window enforcement (only within N hours of departure) | ✅ Complete | Gate 1 (departure exists + `departed_at` set); Gate 2 (now < `departed_at + rating_window_hours`) |
| Fuel and mileage logging | ✅ Complete | `FuelMileageLog` with odometer start/end and fuel added |
| Mobile-responsive field ops UI | ❌ Missing | No PWA hooks, no offline support, no mobile breakpoints tested |

---

## 5. Management Tooling

| Capability | Status | Notes |
|------------|--------|-------|
| Employee create / invite | ✅ Complete | Cognito account creation, `pending_verification` lifecycle, email verification, Discord server invite on first login |
| Employee edit / deactivate | ✅ Complete | Wrong-email recovery for pending accounts; role sync |
| Bulk import (CSV / Excel / JSON) | ✅ Complete | UI-based 3-step modal (upload → preview/edit → results); 200-row cap; per-row independent processing |
| 7-day expired invite cleanup | ✅ Complete | Celery Beat daily task deletes stale `pending_verification` accounts |
| Incident reporting | ✅ Complete | Multi-category (vehicle, injury, theft, customer complaint, route issue, crew conduct, safety hazard); severity levels; photo support |
| Training assignment and session tracking | ✅ Complete | `TrainingRecord`, `TrainingTask`, trainer/manager comments |
| Training curriculum management UI | ❌ Missing | `TrainingCurriculum` model exists in DB; no frontend page to create, edit, or delete curriculum entries |
| Audit log (backend) | ✅ Complete | Immutable `AuditLog` table records actor, action, before/after snapshots for all state changes |
| Audit log UI (frontend) | ❌ Missing | No frontend page to browse or filter audit entries; backend endpoint exists |
| Walker performance analytics | ✅ Complete | `WalkerPerformance.tsx` aggregates ratings, attendance trends, per-walker reliability |
| Driver performance analytics | ❌ Missing | Raw data exists (`Departure`, `VehicleInspection`, `FuelMileageLog`, `Incident`) but no aggregation endpoints or frontend page |
| Preference management and analytics | ✅ Complete | Fav/ban relationships, mutual detection, `Preferences.tsx` with coverage breakdown |
| Preference weight configuration | ❌ Missing | Algorithm weights are hardcoded constants; no admin surface to tune them |

---

## 6. Employee Account Lifecycle

| Capability | Status | Notes |
|------------|--------|-------|
| `pending_verification → active` on first login | ✅ Complete | Cognito sub stamping triggers status flip and Discord invite |
| `active → deactivated` | ✅ Complete | Deactivation endpoint; `is_active = False` |
| Email verification via Cognito | ✅ Complete | Admin creates account without `email_verified: true`; Cognito sends verification email |
| Discord server invite on first login | ✅ Complete | Bot `/internal/invite` webhook; single-use invite link DM'd to `discord_id` |
| Expired invite cleanup (7-day TTL) | ✅ Complete | Celery Beat daily at 3 AM |
| Self-service password reset | ⚠️ Partial | Cognito supports this natively; not surfaced or documented in frontend UX |

---

## 7. Training System

| Capability | Status | Notes |
|------------|--------|-------|
| Daily training record creation | ✅ Complete | Training record per trainee per day |
| Task completion tracking | ✅ Complete | `TrainingTask` with `is_completed`, `is_mandatory`, `is_training_debt` |
| Training debt escalation | ✅ Complete | Missed mandatory tasks flagged; escalated in dispatch algorithm priority |
| Trainer / manager comments | ✅ Complete | Separate comment fields on `TrainingRecord` |
| Trainee dashboard | ✅ Complete | `TraineeDashboard.tsx` shows progress, tasks, and history |
| Continuation request (trainer requests to keep trainee) | ✅ Complete | `TrainerContinuationRequest` model + approval workflow |
| Curriculum management UI | ❌ Missing | Can't add/edit curriculum days through the UI |
| Trainee graduation notification | 💡 Implied | Graduation logic exists but no notification to trainee, trainer, or management on promotion |

---

## 8. Infrastructure

| Capability | Status | Notes |
|------------|--------|-------|
| Docker containerization (postgres, redis, backend, bot, celery) | ✅ Complete | All 5 services containerized with health checks |
| Alembic schema migrations (30 migrations) | ✅ Complete | Full migration history from initial schema |
| AWS Cognito authentication | ✅ Complete | Role-based access control; JWT validation; group membership |
| Role-based access control (7 roles) | ✅ Complete | driver, walker, trainer, trainee, dispatch, management, admin |
| Celery Beat scheduled tasks | ✅ Complete | Worker running with `--beat`; invite cleanup task wired |
| Redis caching / task broker | ✅ Complete | Used by Celery |
| Photo storage (base64 in Postgres) | ⚠️ Partial | `photo_url` columns exist on `CheckIn`, `Departure`, `Incident`; storing large base64 strings inline in Postgres is not production-scalable |
| S3 / cloud photo storage | ❌ Missing | Presigned upload URLs not implemented; critical for production at scale |
| Unit / integration test suite | ❌ Missing | Zero test files in codebase |
| Frontend Docker service | ❌ Missing | Frontend is not in `docker-compose.yml`; runs locally only |

---

## 9. What the Proposal Can Honestly Claim

These are the only features that are **built, wired end-to-end, and in working condition**:

- Automated dispatch algorithm (multi-pass, weighted, rule-compliant)
- Dispatcher review and manual publish workflow
- Discord DM delivery with Confirm / Decline buttons
- Live confirmation tracking per truck
- Staff availability panel
- All field operations tracking (check-in, inspection, departure, return, ratings, fuel)
- Rating window enforcement
- Walker performance analytics
- Training system (records, tasks, debt tracking, graduation)
- Incident reporting
- Employee lifecycle management (create, invite, deactivate)
- Bulk employee import (CSV / Excel / JSON)
- Schedule and assignment change request workflows
- Role-based access control across all endpoints
- Preference (fav/ban) management and analytics

---

## 10. Implied Features Not Yet Scoped

These are logical next steps implied by existing architecture. None are started.

| Feature | Why It's Implied |
|---------|-----------------|
| **Automated dispatch scheduling** (run at configured time) | Celery Beat is live; dispatcher manually triggers today |
| **No-show enforcement** (8:20 AM / 9:00 AM Celery tasks) | Deadlines are defined; enforcement is missing |
| **Official crew post at 9:05 AM** | Confirmation flow ends at 9:00; no bot task posts rosters to channels |
| **Inspection failure alert** | `has_failures` is stored; nothing fires on failure |
| **TruckAssignment lifecycle** (`planned → active → completed`) | Status column exists; transitions never wired |
| **Audit log UI** | Backend endpoint exists; no admin page |
| **Training curriculum admin UI** | Model and endpoints exist; no management UI |
| **Driver performance analytics** | Raw data exists across Departure, Inspection, Fuel, Incident; no aggregation |
| **S3 photo migration** | `photo_url` columns exist; base64 inline storage won't scale |
| **Preference weight configuration UI** | Algorithm constants are hardcoded |
| **Standby driver pool** | No-show protocol requires one; not modeled |
| **Mobile-responsive field ops** | Drivers use field ops on phones; no mobile-first design |
| **Unit test suite** | Core dispatch algorithm is complex; zero test coverage |
| **Payroll / compensation tracking** | Not started; no model, no data |
| **Anchor Point (AP) recording** | Driver posts AP manually to Discord; not stored in DB |
| **`late` confirmation status** | `confirmed` vs. `physically present` distinction unmodeled |
| **Geo-check for crew proximity** | Implied by crew confirmation vs. AP arrival question |

---

## 11. Known Bugs (From `discussion.md` and Code Review)

| Bug | Location | Status |
|-----|----------|--------|
| `TruckAssignment.status` never transitions from `planned` | `truck_assignments.py` / no departure hook | ❌ Not fixed |
| Fleet Today card shows 0/0 | `AdminDashboard.tsx` — queries status that's always `planned` | ❌ Blocked by status bug above |
| Dispatch drag-and-drop assigns correct role | `DispatchDashboard.tsx:233` — uses actual employee role, falls back to `walker` | ✅ Not a bug — defensive fallback only |
| `available_pool` PTO filtering | `available_pool.py` — filters approved PTO | ✅ Already working — not a bug |

---

*This document should be updated whenever a feature is completed, partially implemented, or descoped.*
