# 2026-05-04 — Mobile App Build-Out: Training, Schedule, and Navigation

## What happened

Full-day mobile development session covering four areas: training screen data fixes, UI/UX redesign across all screens, schedule screen parity with web, and navigation rewiring so all trainer/trainee sub-screens are actually reachable.

---

## 1. API connectivity fixes (carried over from previous session)

### Root causes

Two blockers were preventing any data from loading:

- **Wrong API base URL** — `.env` had `ASHEFLOW_API_URL=http://10.0.2.2:8000/api/v1` (Android emulator address). iOS simulator uses `localhost` directly.
- **Wrong JWT token type** — `mobile/src/api/client.ts` was sending `asheflow_access_token` as the Bearer token. Access tokens don't carry `cognito:groups`, so the backend `RoleChecker` returned 403 on every role-gated route. Fixed to `asheflow_id_token`.

### Fix

`mobile/.env`: changed base URL to `http://localhost:8000/api/v1`.  
`mobile/src/api/client.ts`: changed Bearer token key from `access_token` → `id_token`.

**Key lesson:** `id_token` and `access_token` are not interchangeable in Cognito. The id_token carries `cognito:groups`, `email`, and user attributes. The access_token is for service authorization only and carries none of that. Always use id_token when the backend reads group membership from the JWT.

---

## 2. Training screen field name fixes

All training screens had field name mismatches against the actual backend response shapes. Fixes applied across `TrainerTodayScreen`, `TraineeTodayScreen`, `TrainerHistoryScreen`, `TraineeHistoryScreen`, `TrainerPerformanceScreen`.

| Wrong field | Correct field | Endpoint |
|---|---|---|
| `topic` | `topic_title` | tasks array |
| `is_debt` | `is_training_debt` | tasks array |
| `completed` | `is_completed` | tasks array |
| `day_number` | `current_day_number` | record |
| `POST /training/record/{id}/task` | `PATCH /training/task/{task_id}` | task toggle |
| `{ comment }` | `{ comments }` | trainer-comments |
| flat array | `[{trainee, sessions: [{record, tasks}]}]` | trainer history |
| `standing` | `underperforming` | trainer-marks summary |
| `trainees_affected` | `distinct_trainees_with_marks` | trainer-marks summary |

Also: `GET /dispatch/{date}` is `allow_dispatch_mgmt` only — field staff get 403. Today's Assignment must use `GET /schedule/{employee_id}?start_date=&end_date=` instead. Schedule endpoint also requires local date (not UTC — `new Date().toISOString()` gives yesterday in US timezones).

---

## 3. UI/UX redesign

### ScreenShell

Converted from a large scrolling title to a fixed header bar with a bottom border. Title stays anchored; `noHeader` and `edges` props added so embedded screens don't double-render safe area or headers when hosted inside a dashboard wrapper.

### Task lists (TrainerTodayScreen, TraineeTodayScreen)

Replaced flat divider-only row lists with:
- **Grouped card containers** — all tasks in a section share one rounded card (`overflow: hidden`), rows separated by inset dividers only (no border on last row). Pattern from Things 3 / iOS Settings.
- **Expand/collapse on row tap** — description hidden by default, `▼`/`▲` chevron when description exists, `numberOfLines` removed so full text shows when expanded.
- **Independent checkbox touch target** — `TouchableOpacity` on the circle with `hitSlop: 8px` so tapping the circle toggles completion without expanding the row.
- **Debt task accent** — 3px red left border bar per row (not background wash on the whole card).
- **Hero card** — trainee/trainer avatar initials + name + large `X/Y` fraction + 4px progress bar.
- **`is_locked` support** — locked badge on hero card, checkboxes disabled (grayed), handoff textarea hidden, existing note shown as read-only banner.

### Schedule screen

Added parity with the web:
- **Day circles** — every calendar day is now a 34px circle. Filled green tint for scheduled workdays (previously no indicator at all), solid primary for today, orange tint for PTO pending, red tint for off/PTO, selection ring for tapped day.
- **Selected day detail card** — tapping any day shows a card below the calendar with status pill, truck name, and full crew list grouped by role with colored role dots. Matches the web's detail panel exactly.
- **Legend** — added "Workday" (green) as first entry.
- **PTO trigger** — only opens modal when tapping a future scheduled workday, not any future day.
- **Fixed header** with month subtitle.
- **Request lists** — moved from individual bordered cards to grouped card with inset dividers.

### Trainer history screen

Rewrote to match web's two-level structure:
- **Trainee group accordion** — one card per trainee with aggregate stats (total sessions, overall task completion %, avg star rating, last session date). Tap to expand.
- **Session row accordion** — inside each group, session rows show day number, date, debt count badge, escalated task warning (⚠), completion fraction, and trainee star rating. Tap to expand.
- **Expanded session detail** — full task list with ✓/✗ per task (debt tasks in red, completed tasks struck through), trainer's handoff note, trainee review with stars, manager note. Previously none of this was visible on mobile.

---

## 4. Navigation rewiring

### Problem

`TrainerHistory`, `TrainerPerformance`, `Phase4`, and `TraineeHistory` were all registered as React Navigation stack screens, but nothing in the codebase ever called `navigation.navigate()` to reach them. They were completely unreachable dead screens.

### Fix

Created `TrainerDashboard` and `TraineeDashboard` wrapper components. Each owns the `SafeAreaView`, a fixed header, and a horizontal tab bar — mirroring the web's tab structure on `/trainer-dashboard` and `/my-training`.

**TrainerDashboard tabs:** Today · History · Performance · Phase 4 (conditional)  
**TraineeDashboard tabs:** Today · History

Phase 4 tab appears only when `GET /training/trainer/today` returns `record.current_day_number === 4`, identical to how the web navbar conditionally shows the Phase 4 link.

Both navigator functions now register a single screen (`headerShown: false`) pointing to the dashboard wrapper. The old multi-screen stack registration is gone.

---

## Files changed

### New files
- `mobile/src/screens/Trainer/TrainerDashboard.tsx`
- `mobile/src/screens/Trainee/TraineeDashboard.tsx`
- `mobile/src/screens/Home/TodayAssignmentScreen.tsx`

### Modified files
- `mobile/src/navigation/index.tsx` — TabSwitchContext, HomeNavigator stack, TrainerDashboard/TraineeDashboard routing
- `mobile/src/components/ui/ScreenShell.tsx` — `edges` and `noHeader` props
- `mobile/src/screens/Home/HomeScreen.tsx` — summary cards, useTabSwitch, local date
- `mobile/src/screens/Trainer/TrainerTodayScreen.tsx` — field names, is_locked, task group UI
- `mobile/src/screens/Trainer/TrainerHistoryScreen.tsx` — two-level accordion, full task list, aggregate stats
- `mobile/src/screens/Trainer/TrainerPerformanceScreen.tsx` — correct summary fields
- `mobile/src/screens/Trainee/TraineeTodayScreen.tsx` — field names, task group UI, expand/collapse
- `mobile/src/screens/Trainee/TraineeHistoryScreen.tsx` — review submission, window logic
- `mobile/src/screens/Schedule/ScheduleScreen.tsx` — day circles, selected day card, crew display
- `mobile/.env` — API base URL
- `mobile/src/api/client.ts` — id_token Bearer
