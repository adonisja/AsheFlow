# Analytics Access Audit

**Date:** 2026-04-23  
**Scope:** Every analytics surface (KPI cards, charts, panels, tables) across all pages and roles.  
**Purpose:** Verify each datapoint is visible to the correct roles, flag mismatches, and identify gaps.

---

## Role Hierarchy Reference

| Role | Description |
|---|---|
| `admin` | Full system access, can emulate any view |
| `management` | Operational oversight — fleet, training, compliance, performance |
| `dispatch` | Daily crew assignment and confirmation tracking |
| `trainer` | Manages trainee sessions |
| `trainee` | Views own training progress only |
| `driver` | Field staff — check-in, field ops, schedule |
| `walker` | Field staff — same as driver |

---

## 1. Home Dashboard — Shared KPI Row (`/`)

All authenticated users see this on the root `/` page.

| Card | What It Shows | Access | Verdict |
|---|---|---|---|
| Role | User's assigned groups | All authenticated | ✅ Fine — informational only |
| Status | Hardcoded "Active" | All authenticated | ⚠️ **Not real data.** Always says "Active" regardless of whether the employee is actually active in DB. Consider deriving from employee record or removing. |
| Today | Today's date | All authenticated | ✅ Fine |

---

## 2. Dispatch View — Home Dashboard (`/`, dispatch branch)

Visible on `/` when the user is in the `dispatch` group, or when an `admin` switches to the dispatch tab.

| Panel | What It Shows | Access | Verdict |
|---|---|---|---|
| Pending Approvals | Count + list of pending time-off, off-day, and assignment-change requests | Dispatch, Admin | ✅ Correct — dispatch needs to act on these |
| Active Incidents | Count + list of unresolved urgent incidents | Dispatch, Admin | ✅ Correct — dispatch needs situational awareness |
| Fleet Return Status | Per-truck return status (driver, returned/out, duration) | Dispatch, Admin | ✅ Correct — dispatch tracks end-of-day truck returns |

---

## 3. Management View — Home Dashboard (`/`, management branch)

Visible on `/` when the user is in the `management` group, or when an `admin` switches to the management tab.

| Card/Panel | What It Shows | Access | Verdict |
|---|---|---|---|
| Active Trainees KPI | Total trainees in training + sessions today | Management, Admin | ✅ Correct |
| Incidents (7d) KPI | Total incidents last 7 days + unresolved count | Management, Admin | ✅ Correct |
| Fleet Today KPI | Trucks returned vs total out | Management, Admin | ⚠️ **Known bug** — currently shows 0/0 due to unresolved yard-presence vs departure-activity semantics. Needs fix before this card is meaningful. |
| Escalated Trainees KPI | Count of trainees needing manager review | Management, Admin | ✅ Correct |
| Incident Trend (7d) | Severity breakdown + top 5 categories | Management, Admin | ✅ Correct |
| Walker Performance (This Week) | Presence rate, no-shows, avg stars per walker | Management, Admin | ✅ Correct |
| Training Pipeline | Trainer load today + escalated alert | Management, Admin | ✅ Correct |
| Pre-Trip Inspections Today | Pass/fail count + per-inspection table | Management, Admin | ✅ Correct |
| Inspection Failure Patterns (7d) | Most common failure items + rates | Management, Admin | ✅ Correct |

---

## 4. Dispatch Home (`/dispatch-home`)

**Allowed roles:** `admin`, `dispatch`

| Card/Panel | What It Shows | Access | Verdict |
|---|---|---|---|
| Assigned Today KPI | Total crew members in today's dispatch | Dispatch, Admin | ✅ Correct |
| Confirmed KPI | How many crew members confirmed their assignment | Dispatch, Admin | ✅ Correct |
| Pending KPI | How many haven't responded yet | Dispatch, Admin | ✅ Correct |
| Open Incidents KPI | Count of unresolved incidents | Dispatch, Admin | ✅ Correct — dispatch needs to know if anything is active |
| Today's Dispatch panel | Per-truck crew list with driver/crew breakdown + warnings | Dispatch, Admin | ✅ Correct |
| Confirmations panel | Progress bars for confirmed/pending/declined + declined list | Dispatch, Admin | ✅ Correct |
| Staff Off Today panel | Who is unavailable today and why | Dispatch, Admin | ✅ Correct — critical for understanding assignment gaps |
| Pending Schedule Changes | List of pending swap/change requests | Dispatch, Admin | ✅ Correct |

---

## 5. Operations Analytics (`/operations-analytics`)

**Allowed roles:** `dispatch`, `management`, `admin`

This is the biggest role access issue in the system. The page is fully visible to all three roles, but several panels are not relevant to dispatch.

| Panel | What It Shows | Should Dispatch See It? | Should Management See It? | Verdict |
|---|---|---|---|---|
| **Dispatch Fill Rate** | Algo vs manual assignments over time (4–12 week window) | ✅ Yes — directly about their process | ✅ Yes — operational health | ✅ Correct |
| **Trainer Load** | How many active trainees each trainer currently has, broken down by phase | ❌ **No** — dispatch does not manage trainers or training phases. This is a management/admin concern. | ✅ Yes | ⚠️ **Misaligned.** Dispatch can see trainer workload data they have no authority or context to act on. |
| **Ban Override Frequency** | How often the dispatch algorithm was overridden because of crew ban preferences | ✅ Yes — it reflects pressure on their algorithm | ✅ Yes — signals preference policy problems | ✅ Correct for both |
| **Confirmation Response Time** | Median and P90 minutes for crew members to respond to dispatch DMs, broken down by role | ✅ Yes — slowest responders affect dispatch timing | ✅ Yes — can inform scheduling expectations | ✅ Correct for both |

**Recommendation:** Either filter the Trainer Load panel out for dispatch users at the component level, or split the page into role-scoped views. Given that Trainer Load is a pure management/admin concern, the simplest fix is a role check inside `TrainerLoadPanel` that only renders for `management` and `admin`.

---

## 6. Admin Dashboard (`/admin`)

**Allowed roles:** `admin` only

| Card/Panel | What It Shows | Verdict |
|---|---|---|
| Active Employees KPI | Count of is_active employees | ✅ Correct — admin only |
| Active Trucks KPI | Count of is_active trucks | ✅ Correct |
| Open Incidents KPI | Count of unresolved incidents | ✅ Correct |
| Training Today KPI | Count of training sessions today | ✅ Correct |
| Workforce Breakdown | Per-role employee count with percentage bars + inactive list | ✅ Correct — admin-level headcount view |
| Open Incidents panel | Max 5 unresolved incidents with inline resolve | ✅ Correct |
| Training Sessions Today | Per-session trainee + trainer + progress bar | ✅ Correct |

---

## 7. Walker Performance (`/walker-performance`)

**Allowed roles:** `management`, `admin`

| Card/Panel | What It Shows | Verdict |
|---|---|---|
| Total Walkers KPI | Count with graded/ungraded breakdown | ✅ Correct |
| Fleet Avg Rating KPI | Overall star average across all shifts | ✅ Correct |
| Fleet Presence KPI | Average presence rate across all walkers | ✅ Correct |
| At Risk KPI | Walkers with D/F grade or ≥3 no-shows | ✅ Correct |
| Grade Distribution chart | A–F bar chart with counts | ✅ Correct |
| At-Risk callout | Clickable list of at-risk walkers | ✅ Correct |
| All Walkers leaderboard | Sortable/searchable/paginated table of all walkers | ✅ Correct |
| Walker Profile panel | Per-walker KPIs, rating history, driver consistency analysis | ✅ Correct |

**Notable absence:** Walkers themselves cannot see their own performance data. A walker can see their schedule and field ops but has no way to know their own grade, presence rate, or how drivers have rated them. This is a gap — see suggestions below.

---

## 8. Vehicle Compliance (`/vehicle-compliance`)

**Allowed roles:** `management`, `admin`

| Card/Panel | What It Shows | Verdict |
|---|---|---|
| Total Inspections KPI | Count for selected period | ✅ Correct |
| Pass Rate KPI | % passed with pass/fail counts | ✅ Correct |
| Trucks w/ Repeat Failures KPI | Count of trucks failing ≥2 times | ✅ Correct |
| Drivers w/ Repeat Failures KPI | Count of drivers with ≥2 failures | ✅ Correct |
| Most Frequently Failed Items | Grid of top failure categories with rates | ✅ Correct |
| Failure Pattern Heatmap | Item × Truck or Item × Driver matrix | ✅ Correct |
| Repeat Offenders | Trucks and drivers with most failures | ✅ Correct |
| Inspection History Table | Per-inspection expandable detail | ✅ Correct |

**Notable absence:** Drivers who fail inspections have no visibility into their own inspection history or failure patterns. A driver failing the same item repeatedly has no feedback loop unless management tells them directly.

---

## 9. Trainer Marks (`/trainer-marks`)

**Allowed roles:** `management`, `admin`

| Card/Panel | What It Shows | Verdict |
|---|---|---|
| Underperforming alert | Count of flagged trainers (marks across 3+ distinct trainees) | ✅ Correct |
| Trainer summary cards | Per-trainer mark count and distinct trainee count | ✅ Correct |
| Marks table | All marks with trainer, trainee, phase, date, reason, context | ✅ Correct |

**Notable absence:** Trainers cannot see their own marks or whether they're flagged as underperforming. A trainer has no self-awareness from the system unless management brings it up. See suggestions below.

---

## 10. Trainer Dashboard (`/trainer-dashboard`)

**Allowed roles:** `trainer`, `admin`

| Panel | What It Shows | Verdict |
|---|---|---|
| Today's session card | Trainee name, day number, lock state | ✅ Correct |
| Handoff note | Previous trainer's comments | ✅ Correct |
| Task checklist | Today's tasks (read-only if locked) | ✅ Correct |
| Trainer note editor | Compose handoff note for next session | ✅ Correct |
| History — trainee cards | Sessions per trainee: completion rate, avg rating, last session | ✅ Correct |
| History — session breakdown | Per-session tasks, trainer notes, trainee review, manager notes | ✅ Correct |

---

## 11. Trainee Dashboard (`/my-training`)

**Allowed roles:** `trainee` only

| Panel | What It Shows | Verdict |
|---|---|---|
| Today's shift header | Day number, paired trainer name | ✅ Correct |
| Task checklist | Today's tasks (read-only) | ✅ Correct |
| Training history | Past sessions with task lists, trainer ratings, review form | ✅ Correct |

---

## Role Access Mismatches Summary

| # | Issue | Severity | Fix |
|---|---|---|---|
| 1 | **Trainer Load panel visible to dispatch** | Medium | Add in-component role check — only render for `management`/`admin` |
| 2 | **"Status" KPI is hardcoded "Active"** | Low | Either derive from employee record or remove the card |
| 3 | **Fleet Today KPI shows 0/0** | High | Resolve yard-presence vs departure-activity semantics (tracked separately) |
| 4 | **Walkers have no access to own performance data** | Medium | Add a walker-facing view (see suggestions) |
| 5 | **Drivers have no access to own inspection history** | Medium | Add a driver-facing field ops panel or page section |
| 6 | **Trainers cannot see own marks or flag status** | Medium | Add a self-assessment section to Trainer Dashboard |

---

## Suggestions: New Analytics Datapoints by Role

### For Dispatch

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **Declined rate over time** | % of published assignments that get declined per week | Identifies if certain days or certain crew mixes are consistently declining — signals scheduling or preference problems |
| **No-show rate by day of week** | Heatmap of absences Mon–Sun over rolling 12 weeks | Helps dispatch anticipate coverage gaps on historically thin days |
| **Avg time to full confirmation** | How long after publish before all crew have responded | Helps dispatch know when they can safely finalize |
| **Manual override rate by truck** | Which trucks need the most manual crew adjustments | Signals trucks that the algorithm consistently can't fill well (ban clusters, driver preferences) |

### For Management

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **Walker grade trend** | Grade trajectory per walker over 4–12 weeks (improving / declining) | Catches walkers trending toward at-risk before they hit D/F |
| **Trainer effectiveness score** | Avg trainee completion rate and avg trainee rating per trainer | Identifies which trainers produce better-prepared graduates |
| **Trainee graduation pipeline** | Expected graduation dates based on current assignment cadence | Lets management plan for upcoming walker additions |
| **Incident resolution time** | Avg hours from incident filed to resolved, by category | Identifies bottlenecks in incident handling |
| **Schedule change request approval rate** | % approved/rejected with avg response time | Keeps management aware of how long requests sit unaddressed |

### For Trainers (self-view, scoped to own data)

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **My marks summary** | Count of marks filed against me, which trainees, which phases | Trainers currently have zero visibility into their own performance flags |
| **My trainee outcomes** | Graduation rate and avg rating of trainees I've trained | Lets trainers see whether their trainees succeed after training |
| **Avg trainee rating for my sessions** | Trainee-submitted stars + comments from my sessions | Feedback loop trainers currently lack |

### For Walkers (self-view, scoped to own data)

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **My performance summary** | Own grade, presence rate, no-show count, avg star rating | Walkers currently have no visibility into how they're being evaluated |
| **My rating history** | Per-shift driver ratings and comments about me | Lets walkers understand what drivers are saying and self-correct |
| **My streak** | Consecutive shifts present without a no-show | Positive reinforcement and engagement |

### For Drivers (self-view, scoped to own data)

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **My inspection history** | Own pass/fail record with failure items | Drivers currently have no feedback on their pre-trip inspection performance |
| **My fuel/mileage log** | Own submission history with totals | Self-auditing and accountability |
| **My confirmation response time** | Own avg and trend vs fleet avg | Encourages faster responses to dispatch DMs |

### For Admin

| Suggestion | What It Would Show | Why It Helps |
|---|---|---|
| **User activity heatmap** | Login frequency per user over 30/60/90 days | Identifies inactive accounts that may need deactivation |
| **Algorithm health over time** | Fill rate + override rate + decline rate combined into one view | Single-pane view of dispatch system health |
| **Role distribution over time** | Snapshot of how headcount per role has changed month-over-month | Useful for staffing trend awareness |
