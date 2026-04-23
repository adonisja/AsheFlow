## 2026-04-22 Bot DMs: Trainer-Trainee Pairing Callout and Simulation Reset

This section was written after addressing the trainer-trainee notification gap and the reset_on_graduation flag (ADR-047).

---

### The pairing gap in dispatch DMs

The dispatch bot DMs each employee a crew roster when assignments are published. But the roster is just a list — no explicit callout of who is paired with whom for training purposes. A trainer scanning a 10-person crew roster had to infer their trainee; a trainee had no idea who to approach when they arrived at the truck.

The fix is role-specific pairing blocks appended to the DM description:

- **Trainee DM** shows `🎓 Your trainer today:` with the trainer names. If no trainer is on the truck, it shows a warning so the trainee knows to contact dispatch.
- **Trainer DM** shows `📋 Your trainee(s) today:` with each trainee's name and their current training phase (fetched live from `GET /training/trainee/{id}`).

The phase lookup is non-blocking — if the API call fails, the phase shows as `?` and the DM still sends. The cost is one extra HTTP round-trip per trainer at publish time, acceptable for a typical crew size of 1–3 trainers.

### Why not send the pairing callout post-confirmation?

The alternative is to wait until a trainee confirms, then DM their trainer with the phase info. This avoids wasting API calls on employees who decline, and ensures the trainer only gets the callout for trainees who are actually showing up.

The tradeoff: you need bot-side state to correlate the confirmation event back to the trainer. The current design fires at publish time — simpler, slightly wasteful, but never blocks or loses a notification. Revisit if volume grows.

### reset_on_graduation: cycling simulation accounts without polluting the walker roster

The graduation service unconditionally promotes any trainee with 5+ dispatches to walker. For a simulation account used in integration testing (Timmy Trainee), this is wrong — promotion removes them from the training system permanently.

`reset_on_graduation = True` on an `Employee` tells `graduate_trainees.py` to delete all training records for that trainee instead of promoting them. The next dispatch injection sees no open record and reinjects Phase 1 — the full training cycle restarts cleanly.

**Why hard-delete records instead of a soft-reset field?** `training_injection.py` reads `last_record.current_day_number` to determine next phase. A stale record with `current_day_number = 4` would cause Phase 4 to reinject instead of Phase 1. Hard-deleting is simpler and correct for simulation use.

---

## 2026-04-22 Training System: Phase-Based Gating, Debt Attribution, and Trainer Accountability

This section was written after the training system phase-based redesign (ADR-046).

---

### Why calendar-day gating was wrong for this operation

The original training system incremented `day_number` linearly — Day 1 on Monday, Day 2 on Tuesday. This produced false debt whenever a trainer covered early. If Phase 1 was completed by noon and a trainer previewed Phase 2 topics that afternoon, the system would flag those Phase 2 topics as "debt" on Day 2.

The fix: **phases are curriculum units, not calendar dates.** A phase advances when all mandatory tasks are complete, regardless of the date. The `training_injection.py` service checks `last_record.phase_closed` — not `last_record.record_date + 1`.

This also means missed days are free. If a DA calls out, training simply pauses. No debt, no penalty. The clock only runs on days the DA is physically dispatched.

### Debt attribution: one mark per incident, context only downstream

The instinct when a debt chain persists across multiple trainers is to mark every trainer who failed to close their phase. This is wrong — it penalizes trainers for someone else's failure.

The correct model: one mark goes to the trainer who originated the chain (failed with no inherited debt). Everything downstream is context, not punishment. The `debt_chain_context` field on `TrainerMark` documents the impact; the `debt_originated` flag identifies the root cause. Subsequent trainers who fail to close because of inherited debt receive no mark.

This preserves trainer accountability without creating a perverse incentive: under the wrong model, inheriting debt would always result in a mark regardless of effort.

### Topic-level coverage logging enables handoff tracing

The original design assumed the `trainer_id` on a `TrainingRecord` covered all topics on that record. When a trainer leaves mid-shift and a second trainer picks up, this assumption breaks. You lose the handoff point entirely.

`TrainerCoverage` writes one row per topic per trainer at completion time. The handoff is visible in the log as a timestamp boundary — topics covered before 11 AM by Trainer A, topics covered after 2 PM by Trainer B. End-of-day attribution for mark purposes follows whoever was active last.

### Phase 4 is observation, not instruction

Phase 4 tasks are not seeded statically in `training_curriculums`. They are generated at dispatch time in `training_injection.py` by mirroring all mandatory Phase 1–3 items as `record_type = "demonstration"` tasks. This means the Phase 4 checklist automatically reflects any changes to the Phase 1–3 curriculum — no manual sync required.

On submission, `score_phase4()` computes pass/fail (90% threshold, all mandatory items must individually pass). On fail, `generate_remediation_record()` creates a Phase 5 record containing only the failed topics — targeted remediation, not a full restart.

---

## 2026-04-18 Bulk Operations: Parse Client-Side, Validate Before Sending, Report Per-Row

This section was written after building the bulk employee import flow.

---

### Parse files in the browser, not on the server

A common instinct is to send the raw file to the server and parse it there. This adds multipart upload handling, a file parsing dependency in the backend, and a new failure mode (file too large, wrong encoding). None of that buys you anything.

The browser can parse CSV and Excel perfectly well before a single byte is sent to the API:
- `papaparse` — streaming CSV parser, handles encoding edge cases and quoted commas correctly
- `xlsx` (SheetJS) — reads `.xlsx`, `.xls`, and Google Sheets exports, converts to plain JS objects

The backend receives a clean JSON array. It never sees the file.

### Normalize column names before validation, not after

HR spreadsheets use inconsistent headers: "Phone Number", "phone", "mobile", "cell". Rejecting anything that isn't an exact match forces HR to reformat their data before importing. Instead, build a normalization map upfront:

```ts
const ALIASES: Record<string, keyof ImportRow> = {
  phone:        'phone_number',
  mobile:       'phone_number',
  discord:      'discord_id',
  full_name:    'name',
  position:     'role',
  // ...
};
```

Normalize first, validate second. The user never sees column mapping errors — only data errors.

### Validate before the network call, not after

Showing validation errors in a preview table before the user clicks Import is strictly better than surfacing them from the API response. The user can fix mistakes in the browser without a round trip. The API still validates (defense in depth), but it should rarely see bad data from the UI.

### Individual row failures should never abort the batch

If row 34 has a Cognito error, rows 35–70 should still be processed. A batch that fails atomically on one bad row forces HR to fix that row, re-upload, and risk re-processing rows that already succeeded.

The endpoint processes each row independently, accumulates results, and always returns 200 with a per-row outcome array. HR gets a clear report of what happened and can re-import only the failed rows.

### Always give the user a paper trail for batch operations

After a 70-employee import, HR needs to know exactly which accounts were created, which were skipped (already existed), and which failed. The results table is enough for review — but "Export results" as a CSV gives them a file they can attach to an onboarding ticket or share with a manager.

---

## 2026-04-18 Account Lifecycle States and Scheduled Cleanup with Celery Beat

This section was written after implementing email verification, pending account states, and automated invite expiry.

---

### Don't trust what you haven't verified

The original flow stamped `email_verified: true` on the Cognito user at creation time. This pre-trusts the email before anyone has proven they can receive mail at that address. If the admin typo'd the email, the account was permanently broken with no clean recovery path.

The fix: remove `email_verified: true` from `AdminCreateUser`. Let Cognito do what it was built for — send a temp password, require verification on first login. Only when the person successfully logs in do we know the email was real.

### Use explicit state over implicit boolean inference

`is_active = False` means two different things: "hasn't verified yet" and "was active, got deactivated." Code that checks `is_active == False` can't tell which. A Celery cleanup job that deletes `is_active = False` employees older than 7 days would silently delete deactivated employees.

The fix: an explicit `account_status` enum — `pending_verification`, `active`, `deactivated`. Now the cleanup query is unambiguous:

```python
db.query(Employee).filter(
    Employee.account_status == "pending_verification",
    Employee.invited_at < cutoff,
)
```

`is_active` stays as a fast boolean for dispatch eligibility checks, but it's derived from `account_status`, not the source of truth.

### The activation moment is a first-class event

"When does an account become active?" should be a deliberate decision, not something that happens as a side effect of a query. In this system, the activation moment is the first time `get_caller_employee` stamps `cognito_sub` — that's the proof that a real person logged in with a verified email. Putting the state transition there means it's atomic with the login, not a separate job that might miss it.

### Celery Beat: the clock and the worker are separate concerns

Beat is just a scheduler — it fires a task message onto the Redis queue at 03:00 UTC. The worker picks it up and executes it. Neither knows about the other's implementation. This separation matters when you scale: if you need two workers for throughput, Beat still fires once. Beat itself is stateless.

For a single-container deployment, `celery worker --beat` runs both in one process. The comment in `docker-compose.yml` explains when to split them.

### Best-effort side effects belong in background threads

The Discord invite webhook fires from a daemon thread in `_send_discord_invite()`. If the bot is down, the thread fails silently after 5 seconds. The login response still completes — the account is still activated. Side effects that don't affect correctness should never block the main path.

---

## 2026-04-18 Time-Gating Business Logic with Config-Driven Windows

This section was written after adding departure-based gating to walker rating submissions.

---

### The pattern: gate on a real-world event, not just calendar time

A naive approach to "only accept ratings today" would check `payload.date == date.today()`. This doesn't prove anything happened — a driver who never left the yard could still submit ratings for the correct calendar date.

The stronger gate checks for a real-world event: did this driver actually depart? Query the `Departure` table for `(employee_id, date)`. If the row doesn't exist or `departed_at` is NULL, the event didn't happen. Reject the request regardless of what date is on the payload.

```python
departure = db.query(Departure).filter(
    Departure.employee_id == payload.driver_id,
    Departure.date == payload.date,
).first()
if not departure or departure.departed_at is None:
    raise HTTPException(status_code=400, detail="...")
```

### Layering a window on top of the event gate

Once you've confirmed the event happened, you can add a staleness window. The key is to anchor the window to the event timestamp, not to midnight or some other arbitrary reference:

```python
window_close = departure.departed_at + timedelta(hours=settings.rating_window_hours)
if datetime.now(timezone.utc) > window_close:
    raise HTTPException(status_code=400, detail="...")
```

This is more accurate than a fixed cutoff time because different drivers depart at different times.

### Why the window belongs in config, not in code

A 6-hour hardcoded constant looks reasonable today. But shift patterns change — a new service area might have a 10-hour window. Encoding the value in `pydantic_settings` with a safe default means:

- Development: default kicks in, no `.env` entry required
- Production: set `RATING_WINDOW_HOURS=8` in the environment, no deployment needed
- The default is visible in code review as an explicit value, not a magic number

### Gate ordering matters

In `submit_rating`, the gates run in this order:
1. Ownership (caller must be the driver)
2. Departure exists and `departed_at` is set ← event gate
3. Window is still open ← staleness gate
4. Payload validation (stars range)
5. Same-truck check
6. Duplicate check

Event and staleness gates come early because they're database reads that can short-circuit before more expensive checks. Ownership comes first because it's a security boundary — no query needed beyond the session.

---

## 2026-04-18 Audit Trails: Write Alongside the State Change, Not After It

This section was written after adding `write_audit()` to seven approval endpoints.

---

### The wrong mental model: audit as a separate step

A common mistake is to think of logging as something that happens *after* the action succeeds — a side effect, a fire-and-forget call, something that runs in a background task. This is wrong for audit trails. If the state change commits and the audit write fails, you have a gap in the audit trail with no way to reconstruct it.

### The right model: same transaction

```python
# BAD — two separate commits, audit can succeed without state or vice versa
db.commit()                     # state change lands
write_audit(...)                # might fail
db.commit()                     # audit row lands (or doesn't)

# GOOD — one commit, both land or neither does
write_audit(db, ...)            # appends to session, does NOT commit
db.commit()                     # state change + audit row are atomic
```

`write_audit()` in this codebase takes the session as its first argument and calls `db.add()` but not `db.commit()`. The caller always commits. This is the contract — never commit inside the helper.

### Snapshot only what changed

`before_snapshot` and `after_snapshot` are not full row dumps — they are the fields that actually changed:

```python
write_audit(
    db,
    action_type="pto.approved",
    target_table="time_off_requests",
    target_id=str(db_request.id),
    before={"status": "pending"},
    after={"status": "approved"},
)
```

Full row dumps make diffs unreadable and bloat the JSONB column. Capture the minimum that lets a reviewer reconstruct what happened.

### `action_type` naming: dot-namespaced verbs

`pto.approved`, `schedule_change.rejected`, `incident.resolved` — not `APPROVE_PTO` or `update_status`. The dot namespace lets you filter by prefix (`action_type LIKE 'pto%'`) to pull all PTO-related entries without needing to enumerate every variant.

### Capturing `actor_id` requires not discarding the dependency

Several endpoints had `_: dict = Depends(allow_mgmt)` — the current user dict was discarded because it wasn't needed at the time. Adding audit logging requires the actor's ID. Change `_` to `current_user` and pass `current_user.get("id")` to `write_audit`. This is always a safe change — you are not adding a new dependency, just using the one that was already there.

---

## 2026-04-18 React Rules of Hooks: What Breaks and Why

This section was written after fixing a TDZ `ReferenceError` in `Preferences.tsx`.

---

### The rule

React hooks must be called at the top level of a component — never inside conditions, loops, or after a conditional return. They must also be called in the same order on every render.

### The `const` TDZ mistake

```tsx
// WRONG — useEffect is declared before the const function it calls
useEffect(() => {
  loadPreferences(myId);   // ReferenceError at runtime
}, [myId]);

if (isAdmin) return <PreferenceAnalytics />;  // also wrong — hook appears before this

const loadPreferences = async (id: string) => { ... };  // defined here
```

JavaScript `const` bindings are not hoisted. The function exists in memory from the start of the closure but cannot be accessed until the interpreter reaches its declaration — this window is the Temporal Dead Zone (TDZ). Calling it before the declaration line throws `ReferenceError: Cannot access 'loadPreferences' before initialization`.

### The early return mistake

A conditional return (`if (isAdmin) return ...`) before a hook call is a Rules of Hooks violation even if it seems logically safe. React tracks hooks by call order — if an early return skips a hook on some renders, the order changes and React throws.

### The fix: all hooks first, early returns last

```tsx
// CORRECT — all hooks at top, early return after
const loadPreferences = async (id: string) => { ... };
const loadChangeRequests = async (id: string) => { ... };

useEffect(() => {
  loadPreferences(myId);    // defined above, no TDZ
}, [myId]);

if (isAdmin) return <PreferenceAnalytics />;  // after all hooks — safe
```

`const` helper functions defined in the component body before the hooks that call them are not hooks themselves — they don't need to be at the very top. The rule is about hooks (`useEffect`, `useState`, etc.), not regular functions.

---

## 2026-04-18 Frontend Role Guards: The Navbar Is Not the Auth Layer

This section was written after the navbar overflow fix revealed management tabs had been silently removed.

---

### The problem with removing links from the navbar

When the navbar became overcrowded for admins, the fix was to remove management tool links (Assets, Trainees, Compliance, Walkers). This correctly fixed the overflow — but it also silently removed those links for management users who depended on them.

The root cause: navbar link visibility was controlled by a single `isAdminOrMgmt` boolean. Removing the block removed it for both roles at once.

### Separate role checks, even when they look the same now

```tsx
// WRONG — one block hides the links for both roles
{isAdminOrMgmt && (
  <NavLink to="/assets">Assets</NavLink>
  ...
)}

// RIGHT — separate blocks so each role can be adjusted independently
{isMgmt && (
  <NavLink to="/assets">Assets</NavLink>
  ...
)}
{isAdmin && (
  <NavLink to="/admin">Admin</NavLink>
)}
```

If two roles need the same links today but might diverge tomorrow, separate the blocks now. Merging them saves two lines of JSX but costs you the ability to adjust them independently later.

### The navbar is not the only place to check

Removing a navbar link does not remove access to the route — `ProtectedRoute` in `App.tsx` is the actual guard. A management user who knows the URL can still reach `/assets` even if the navbar link is gone. Always verify that:
1. The route has the correct `allowedRoles` in `App.tsx`
2. The navbar shows the correct links for each role
3. The command palette actions are visible to the correct roles

These three are independent and all must be kept in sync.

---

## 2026-04-11 How to Think About Role Scope When Building Multi-Role Systems

This section was written after a full audit of every tool, route, endpoint, and nav link in the application revealed systematic role scope mistakes. Every mistake here was made by the developer first, then corrected. Use this as a checklist before you ship any feature that touches roles.

---

### The core mistake: designing features first, roles second

The pattern that created the most bugs in this project was: build the feature → add a role check as an afterthought → miss the edge cases.

The correct pattern is the reverse: **define who can do what before you write a line of code.** Ask these four questions about every feature:

1. **Who submits this action?** (which specific roles, not "anyone logged in")
2. **Can they only do it for themselves, or for others?** (ownership)
3. **Are there state preconditions that must be true before they can act?** (business rules, not just roles)
4. **Who can read and review the results?**

If you cannot answer all four before writing the endpoint, you will write the wrong endpoint and then patch it later — which is what happened throughout this codebase.

---

### Mistake 1: Conflating "authenticated" with "authorized"

Several routers in this project were entirely unauthenticated at launch:
- `trucks.py`, `time_off_requests.py`, `employee_off_days.py`, `employee_relationships.py`, `schedule.py`, `notifications.py`

The reasoning was: "authentication is handled by Cognito upstream, so everything that reaches FastAPI is authenticated." This conflates two different things:

- **Authentication** = you are who you say you are (handled by the JWT)
- **Authorization** = you are allowed to perform this specific action (handled by `RoleChecker`)

Any authenticated user — a driver, a walker, a trainee — could have approved their own time-off request, created bans against other employees, or read any employee's notification feed. These are authorization failures, not authentication failures.

**Rule:** Every endpoint needs a `RoleChecker` or `get_caller_employee` dependency. "Authenticated" is not a sufficient access policy on its own.

---

### Mistake 2: Defining role guards at the file level but not wiring them to endpoints

In `field_ops.py`, `allow_driver = RoleChecker(["driver"])` was defined at the top of the file. It was never passed as a dependency to any endpoint. Every submission POST endpoint — check-in, departure, inspection, fuel log, walker rating — could be called by any authenticated user.

The constant existed. The intent was correct. The wiring was missing.

**Rule:** When you define a role constant (e.g., `allow_driver`), immediately trace it to every endpoint it should protect. If you define it and don't use it, it means the protection is incomplete. Unused role constants are a code smell — they signal intent without enforcement.

---

### Mistake 3: Missing ownership checks

`assignment_change_requests.py` had no check that `payload.employee_id == caller.id`. Any walker or trainer could submit a reassignment request on behalf of any other walker or trainer. The role check (walker/trainer only) existed. The ownership check did not.

These are two separate guards and both are needed:

```python
# Role check — is this person allowed to do this at all?
_: dict = Depends(allow_submitter)

# Ownership check — are they doing it for themselves?
if payload.employee_id != caller.id:
    raise HTTPException(status_code=403, detail="You can only submit for yourself.")
```

**Rule:** Role guard answers "can this type of user do this?" Ownership guard answers "can this specific user do this for this specific target?" Both are required for write actions on personal data.

---

### Mistake 4: Letting one role boolean do the work of three

The original dashboard used a single `isManagement` predicate:

```typescript
const isManagement = groups.some(r => ['admin', 'management', 'dispatch'].includes(r));
```

All three roles saw the same UI, the same quicklinks, the same pending approval cards. The result:
- Dispatch saw management report panels they had no business reading
- Management saw the Dispatch Center link implying they should run dispatch
- Admin was routed to the trainer daily task form and trainee progress page

**Rule:** When a system has roles with distinct responsibilities, each role gets its own predicate. Don't group roles together in a boolean unless they genuinely share every permission.

```typescript
// Wrong
const isElevated = groups.some(r => ['admin', 'management', 'dispatch'].includes(r));

// Right
const isDispatch   = groups.includes('dispatch');
const isManagement = groups.includes('management');
const isAdmin      = groups.includes('admin');
```

---

### Mistake 5: Extending field access to roles without verifying the business domain first

ADR-016 opened `/field-ops` to all field staff (driver, walker, trainer, trainee) based on the reasoning that "check-in is for all field staff." This was factually wrong: walkers and trainers meet at the Anchor Point, not the yard. They do not drive the vehicle and do not perform pre-trip inspections. The route was corrected in the very next session.

The mistake was making a technical decision (route access) before verifying the operational reality (where these people actually go in the morning).

**Rule:** Before adding a role to a route or endpoint, ask: does this person perform this action in real life? Not "could they theoretically" but "do they, in the actual workflow?" If the answer requires you to ask someone who knows the domain, ask before you code.

---

### Mistake 6: Forgetting to enforce business preconditions at the API layer

Truck reassignment had:
- ✅ Role check (walker/trainer only)
- ❌ Today-only date guard
- ❌ Active assignment check
- ❌ Ownership check

A walker could submit a reassignment request for a date two weeks in the future, for a day they are not assigned, on behalf of another employee. All three were silent failures — no error, just a bad row in the database.

Business rules belong in the API, not just in the UI. The UI should guide the user (remove the date picker, show a warning if no pending assignment), but the API must reject invalid states regardless of what the UI does.

**Rule:** For every write endpoint, list the preconditions that must be true. Add a check for each one. "The UI prevents this" is not an excuse for a missing backend guard — the API is a public surface and can be called directly.

---

### Mistake 7: Embedding growing features inside unrelated pages

The Schedule Change Request feature started as a single off-day selector inside `Preferences.tsx`. Over time the requirements grew to three modes (add_day, drop_day, full_rework), a current schedule display, selectable day filtering derived from off-day state, a history list, and a reviewer panel. All of this was being embedded inside a page designed for fav/ban and reassignment preferences.

When a feature grows, it needs its own page. The sign that a feature has outgrown its host page is when the host page starts accumulating state variables, API calls, and JSX sections that are not related to the page's core purpose.

**Rule:** Give features their own page when they need more than a simple form + list. The threshold is roughly: two or more distinct modes, or a reviewer workflow, or state that requires multiple API calls to populate.

---

### Mistake 8: Removing state without removing all its dependents

When removing the schedule change section from `Preferences.tsx`, the state variables (`offDays`, `selectedDay`, `changeRequestDate`) were removed first, but the handlers (`handleAddOffDay`, `handleDeleteOffDay`), the useEffect (`loadOffDays`), and the JSX section were still present and still referenced the now-missing state. This caused 15+ TypeScript errors.

**Rule:** When removing a feature from a component, remove all four of its parts together: state, effects, handlers, JSX. They are a set. If any piece remains, it will reference the missing pieces and break. When the deletions are spread across a large file, a full component rewrite is safer than targeted edits.

---

### The role enforcement checklist

Use this before shipping any feature that involves role-gated actions:

**Backend:**
- [ ] Does the endpoint have a `RoleChecker` or `get_caller_employee` dependency?
- [ ] If the action is on personal data, is there an ownership check (`payload.X != caller.id`)?
- [ ] Are business preconditions validated (date constraints, state preconditions, existence checks)?
- [ ] Are all role constants that are defined actually wired to an endpoint?

**Frontend:**
- [ ] Is the route in `App.tsx` gated to the correct `allowedRoles`?
- [ ] Is the nav link in `Navbar.tsx` visible only to the correct roles?
- [ ] Are component sections inside the page guarded by role predicates (not just the route)?
- [ ] Does each role have its own predicate variable (`isDriver`, `isTrainee`), not shared with other roles?

**Domain:**
- [ ] Have you verified with the business domain that each role actually performs this action?
- [ ] Is the feature's scope appropriate for its host page, or does it need its own page?

---

## 2026-04-09 Role-Based Filtering & Non-Destructive Seeding

### Non-Destructive Seeding
When merging test and seed data, always avoid destructive deletes. Instead, upsert or check for existence before inserting. This preserves manual test users and prevents accidental data loss during development.

### Role-Based Filtering (Backend & Frontend)
Business rules (such as who can be favorited or banned) must be enforced at both the backend (API, seed logic) and frontend (UI selection lists). This prevents privilege escalation and ensures a consistent user experience.

### Full-Stack Role Expansion
When adding new roles (e.g., "trainee"), update all enums, database constraints, backend logic, and frontend filters. Failing to do so can cause silent bugs, constraint violations, or crashes.

### Defensive Coding for Role Logic
Always handle unknown or future roles gracefully in backend logic (e.g., with try/except or default dicts) to prevent crashes when new roles are introduced.



## 2026-04-08 Frontend Build & Auth
### Vite vs. Node.js Polyfills
When using legacy cryptographic libraries built for Node.js (like `@aws-crypto/sha256-js` inside AWS Amplify) within a modern frontend bundler like Vite, you'll encounter a missing `global` object error in the browser console.
**Solution:** Vite intentionally breaks from Webpack's behavior by not auto-injecting `window.global`. You can manually polyfill this in `index.html`: `<script>window.global = window;</script>`.

### OAuth Tokens (IdToken vs AccessToken)
AWS Cognito Federated Identity provides two distinct JSON Web Tokens upon successful SSO (like Discord or Google). 
- **AccessToken**: Meant for authorizing AWS API calls natively. **It does not contain custom user claims or groups.**
- **IdToken**: Contains standardized OAuth user profile claims (Email, Username, Subject), and uniquely, the custom `cognito:groups` array required by our FastAPI `RoleChecker`.
**Solution:** The Axios interceptor explicitly pulls the `IdToken` and passes it as a Bearer Token.

### FastAPI CORS Configuration
React runs on `localhost:3000` (or `3001` via Vite), while the FastAPI backend runs on `localhost:8000`. Browsers enforce Cross-Origin Resource Sharing (CORS) policies. A naked FastAPI backend silently blocks all requests from a React domain.
**Solution:** Implementing FastAPI's `CORSMiddleware` explicitly authorizes `OPTIONS` preflight checks, allowing data to flow seamlessly between the Vite frontend and local API runtime.


### Authentication Flows: SRP vs USER_PASSWORD_AUTH
AWS Cognito supports multiple login flows.
- **USER_PASSWORD_AUTH**: The React frontend sends the plaintext password over HTTPS. Safe enough for dev, but standard.
- **USER_SRP_AUTH**: (Secure Remote Password). A zero-knowledge proof algorithm. The password never physically leaves the browser; instead, a mathematical proof of the password is sent. This is Enterprise-grade.

**AWS Amplify v6** defaults to SRP, but it requires explicit configuration in the AWS App Client settings (`ALLOW_USER_SRP_AUTH`). Our temporary dev workaround was overriding the `authFlowType` to `USER_PASSWORD_AUTH`.

## 2026-04-08 Dual-Layer Time-Off Architecture
### Explicit Calendar Date vs. Day of Week Constraints
When scheduling workers, two types of unavailabilities exist in the business domain that cannot be reconciled into a single data model:
1. **Recurring Constraints:** "This employee never works on Tuesdays." (Dependent purely on the 1-7 Day of Week integer).
2. **Explicit PTO Constraints:** "This employee requested May 14th, 2026 off." (Dependent entirely on an exact `YYYY-MM-DD` Calendar Date).

If you attempt to merge them into a single API or database row structure, you run into validation leaks. A worker who inherently doesn't work on Tuesdays could accidentally be allowed to request a PTO day on a Tuesday, which functionally creates overlapping identical statuses or throws the total allocated PTO logic into disarray.

**Solution:** 
Create two distinct physical tables with separate router controllers: `EmployeeOffDay` (for Day Of Week logic) and `TimeOffRequest` (for specific Date logic).
In the specific Date router, manually parse the Python `datetime.strftime("%A")` of the target request, cross-reference it with the employee's `EmployeeOffDay` array, and throw an explicit HTTP 400 Exception (`"You cannot request time off on a day you are already scheduled off"`) before writing to the database. Upon rendering to the user, the single `schedule.py` endpoint fetches both arrays and constructs a single visual string map, distinguishing between `"Off (Recurring)"` and `"Time Off"` to preserve absolute clarity for the UX.

## 2026-04-09 Trainer Dashboard & Curriculum Injection
### Managing State Across a Multi-Day Lifecycle
The **Trainer Dashboard** orchestrates a complex 5-day stateful relationship between Trainers and Trainees. Because Trainees may rotate their assigned Trainer day over day, the `TrainingRecord` table acts as an immutable historical log of training events specific to one calendar day. 
Our Dispatch algorithm natively leverages a dynamic "Curriculum Injection" hook. When the dispatch engine runs, it detects any Trainee allocations and programmatically searches for prior historical training days. It then intelligently rolls over incomplete mandatory tasks—flagged as "Training Debt"—into the current day's record before appending the current day's scheduled curriculum content. This ensures no training gaps occur even as Trainees change trucks or miss days.

### Soft Deleting via Reassignment Bumping (Trainee Overrides)
Manually overriding Trainees via the dispatch portal necessitates structural cascading un-assignments ("bumping"). When a manager manually places a Trainee onto a truck that already features a Trainee, the algorithm safely deletes the prior seating arrangement. It then automatically scans the pool of available trucks for one that possesses a Trainer mapping but lacks a Trainee mapping, and automatically shifts the bumped individual onto that valid fallback truck.

---

## 2026-04-11 Unit Testing the Dispatch Service Layer

### Why SQLite in-memory for a PostgreSQL app
The dispatch services use SQLAlchemy ORM, which is database-agnostic. SQLite in-memory databases (`sqlite:///:memory:`) spin up in milliseconds, need no Docker container, and are fully isolated per test. Each test gets a completely fresh schema — nothing leaks between tests.

The tradeoff: some PostgreSQL-specific column types (`JSONB`, `ARRAY`) cannot be compiled by SQLite. The solution is a **targeted MetaData** approach — build a list of only the tables your services actually touch, copy them into a fresh `MetaData` object via `table.to_metadata(meta)`, and call `meta.create_all(engine)`. Never use `Base.metadata.create_all` in SQLite tests — it will try to create every model, including ones with PostgreSQL-specific types that will crash.

### The working set principle
Service functions build their state (ban maps, crew maps, lookup dicts) once at the start of the call from the inputs they were given. Data inserted *during* the call (e.g., walkers placed mid-loop) is not visible to state built at the top of the function unless the function explicitly re-queries. This is the most common source of confusion when testing services: "I set it up, why doesn't the function see it?" — because the function's working set was already built from the initial inputs.

In `assign_walkers`, the ban map is built once from the initial `assigned_crews`. Walkers placed during the loop don't appear in the ban map for subsequent iterations. This means the walker-vs-walker ban override can only fire for walkers who were already in `assigned_crews` at call time — not walkers placed within the same call. This is a known architectural limitation documented in `TEST_LOG.md`.

### Never rely on random outcomes in tests
`assign_drivers`, `assign_trainers`, and `assign_walkers` use `random.choices` for weighted selection. Any test that asserts which specific truck was chosen must patch `random.choices` using `unittest.mock.patch`. A test that only passes when a particular random outcome occurs is not a test — it is a gamble. It will pass most of the time and fail occasionally, making it worse than useless (it creates false confidence and occasional mysterious CI failures).

```python
with patch("app.services.assign_walkers.random.choices", side_effect=fake_choices):
    assign_walkers(...)
```

The patch target must be the module where `random.choices` is *used*, not where `random` is defined.

### Never mutate ORM objects to represent ephemeral state
SQLAlchemy tracks all attribute changes on session-attached objects. If you do `employee.role = "walker"` to temporarily re-slot a trainer, the next `db.commit()` will permanently write that change to the database — even if you only intended it as in-memory state for the current dispatch run. Use separate data structures (dicts, lists of tuples) for ephemeral dispatch state. ORM objects are DB records, not scratch space.

This was the root cause of the excess-trainer re-slot bug in `run_dispatch`: the code used `t["role"] = "walker"` (dict syntax, which raises `TypeError` on ORM objects) — but even if it had used `t.role = "walker"`, every dispatch with excess trainers would have silently demoted real trainers in the database.

### Test at the right level
- **Unit tests** cover individual services in isolation — ban logic, spread guarantees, weight calculations.
- **Integration tests** cover `run_dispatch` — pipeline wiring, DB write verification, warning thresholds.
- Don't re-test sub-service internals at the integration level. If `assign_trainers` is already tested to enforce even spread, `run_dispatch` doesn't need to verify that again. The integration test checks: did the pipeline call the right things? Did the rows get committed?

### Bugs are most often found at the boundary
All three production bugs found during this test session were at boundaries:
1. The interface between `ban_override.py` and `assign_walkers` (wrong argument count)
2. The interface between the available pool (ORM objects) and the re-slot logic (dict syntax assumption)
3. The interface between `check_ban_override` (returned `True`) and the caller that expected the evicted walker to be re-placed

Boundary bugs are silent because both sides work in isolation — the failure only appears when they're connected. Integration tests and tests that cross function boundaries are what catch these.

---

## 2026-04-14 Dispatch Warning Timing and Trainer Context Design

### Mistake: Warning emitted at code-path entry, not at outcome

In `assign_walkers`, a ban conflict warning was appended as soon as the fallback path was entered — before `selected_truck` was determined. The reasoning was: "we fell back, therefore there must be a conflict." But falling back does not guarantee a conflict. The fallback pool excludes banned trucks; if the fallback pool is non-empty, the walker is placed on an unbanned truck and no conflict occurred.

The result: dispatchers saw a warning that two employees had a ban conflict and were placed together — but looking at the actual crew assignments, they were on different trucks.

**Rule:** Warnings that describe placement outcomes must be placed *after* the placement, conditional on the outcome. "Entered a constrained code path" and "produced a constrained outcome" are not the same thing. Always ask: is this warning logically true at the point I am emitting it?

```python
# Wrong — warns before placement; placement may avoid the conflict
warnings.append({"employee_id": walker.id, ...})
selected_truck = random.choices(...)

# Right — warns only if placement actually landed on a banned truck
selected_truck = random.choices(...)
assigned_crews[selected_truck].append(...)
if selected_truck in hard_banned:
    warnings.append({"employee_id": walker.id, ...})
```

This is a general principle: **side effects (logs, warnings, notifications) belong after the action that determines their truth, not before.**

---

### Literal path segments must be declared before parameterized ones

FastAPI matches routes in declaration order. If you have:

```python
@router.get("/trainer/{trainer_id}/history")  # declared first
@router.get("/trainer/today")                 # declared second
```

A request to `/trainer/today` will try to parse `today` as a UUID for `trainer_id`. FastAPI returns a 422 validation error — it does not fall through to the next route. The literal route is unreachable.

**Fix:** Always declare routes with literal path segments before routes with parameterized segments at the same position.

```python
@router.get("/trainer/today")                 # literal first
@router.get("/trainer/{trainer_id}/history")  # parameterized second
```

The same issue applies to `/employees/me` vs `/employees/{employee_id}` — `me` must come first.

---

### `GET /me` is worth adding early to any multi-role API

The frontend frequently needs to know the authenticated user's own employee UUID — for fetching their history, submitting their own records, and populating forms. Requiring the frontend to derive this from JWT claims or store it in auth context creates coupling between the auth system and every component that needs it.

A `GET /employees/me` endpoint that resolves via the same `get_caller_employee` dependency used throughout the API makes this a single, consistent call. The frontend calls it once on mount, gets the employee UUID, and passes it to any component that needs it.

**Pattern:**
```python
@router.get("/me", response_model=EmployeeResponse)
def get_my_employee(caller: Employee = Depends(get_caller_employee)):
    return EmployeeResponse.model_validate(caller)
```

---

### Handoff notes belong above the task list, not in history

When redesigning the TrainerDashboard, the initial structure placed trainer-to-trainer handoff notes inside the historical log — the trainer would have to scroll past today's tasks and look through past records to find what the previous trainer had written.

This is the wrong priority. A handoff note from the prior session is the most actionable context a trainer has when they sit down with a trainee. It should be the first thing they see — above the checklist, not below it. The UX should mirror the paper handoff: you read the previous shift's notes before you start work, not after.

**Rule:** Surface time-sensitive, actionable context at the top of the view. Historical context belongs below current-day context.

---

### Per-role history is more useful than aggregated history

The original TrainerDashboard showed the current trainee's history across all trainers. The reworked dashboard shows the trainer's history across all trainees.

Both are useful views, but they serve different audiences:
- **Management** needs the trainee-centric view: how is this trainee progressing regardless of who trained them?
- **Trainers** need the trainer-centric view: what trainees have I worked with, how did they do with me specifically, what notes did I leave?

Mixing both into one view for trainers creates noise. A trainer doesn't need to see what other trainers wrote about a trainee they've never worked with — that context belongs in the management hub, not the trainer's personal dashboard.

**Rule:** When designing a dashboard for a specific role, ask what decisions that role needs to make. Build the view around those decisions, not around the complete data model.

---

## 2026-04-14 Role-Specific Views and the Limits of Conditional Hiding

### Mistake: hiding a form is not the same as removing a page section

The `/schedule-changes` page used a single `isReviewer` flag to hide the submission form for management and admin. But the "Your Current Schedule" summary and "My Requests" history sections were rendered unconditionally — they showed the reviewer's own off-days and their own empty request history, which are meaningless for roles that cannot submit requests.

The fix required recognising that `isReviewer` only hid the action, not the context that surrounded it. Management and admin got a page that was 80% personal data they had no stake in, plus 20% reviewer queue at the bottom.

**Rule:** When a role has no personal stake in a page's subject matter, none of the personal sections should render — not just the action buttons. Hiding the form while leaving the surrounding context is an incomplete fix.

---

### Use branched rendering when roles have meaningfully different purposes on the same page

The correct fix for reviewer vs. field-staff on `/schedule-changes` was not to add more conditionals to the existing JSX tree — it was to split into completely separate render paths:

```typescript
if (isAdmin)      return <AdminView />;
if (isManagement) return <ManagementView />;
return <FieldStaffView />;
```

Each branch renders only what that role needs. There is no shared JSX that partially applies to multiple roles. This approach:
- Makes it impossible for personal sections to leak into reviewer views
- Makes each role's view independently readable — you don't have to mentally subtract conditionals to understand what a given role sees
- Makes future changes to one role's view safe — you edit one branch, not a shared tree with many guards

**Threshold:** Split into branches when two roles have different *purposes* on the page, not just different *permissions*. If the difference is "can edit vs. can only view," a conditional is fine. If the difference is "tracks their own data vs. reviews others' data," branch.

---

### Ask whether a role has a personal stake before granting page access

Admin was given access to the `/schedule` page as a default "admins can see everything" posture. But the Schedule page is a personal schedule viewer and PTO request tool — it only makes sense for roles that are dispatched and have a schedule to view.

The check that was missing: **does this role have a personal stake in the subject matter of this page?**

- Drivers, walkers, trainers, trainees: yes — they are dispatched, they have schedules, they submit PTO.
- Management: yes — they view *others'* schedules and check available staff.
- Admin: no — admins are not dispatched, have no personal schedule, and have better tools for availability data.

**Rule:** Before adding a role to a route, ask: does this role perform actions or consume information that this page provides? "Admin can see everything" is not a policy — it is an abdication of design. Admins should have access to the tools they need, not every tool that exists.

---

### Admin and management are both reviewers but not the same reviewer

Admin and management both review and approve schedule change requests. The initial implementation treated them identically (`isReviewer = isAdmin || isManagement`). But they have different oversight functions:

- **Management** needs the operational queue — what requests are pending right now, approve or reject.
- **Admin** needs the organizational view — how many requests, what types, what's the approval rate, which days are most volatile.

Collapsing them to `isReviewer` loses this distinction. Admins got only the queue; management got the queue plus personal sections they had no use for.

**Rule:** When multiple elevated roles share a capability (reviewing), check whether they share the *same purpose* for that capability. If they don't, give them different views. "Both can approve" is not sufficient reason to show them identical pages.

---

## 2026-04-14 Global vs. Intra-Scope Fairness in Assignment Algorithms

### The mistake: assuming global fairness implies local fairness

`assign_trainees` used a global round-robin: pick any trainer whose paired-trainee count equals the current global minimum. This produces system-wide even distribution — no trainer across all trucks ever gets N+1 before every other trainer reaches N.

But it says nothing about trainers *on the same truck*. A trainer can reach count 2 while their truck-mate is still at 1, as long as everyone else globally is also at 1. From the system's view: balanced. From Truck A's crew's view: one trainer is handling twice the workload.

**Rule:** Global fairness guarantees aggregate balance. It does not guarantee fairness within any subgroup. If the unit of operation cares about subgroup balance (a truck's crew, a team's workload), you must add a subgroup-level constraint explicitly.

---

### The fix: two-level eligibility

The correct pattern for assignment with hierarchical fairness:

1. **Outer scope minimum** — eligible only if at the global minimum across all entities.
2. **Inner scope minimum** — eligible only if at the minimum within your own subgroup (truck, team, region).

A trainer blocked by rule 2 cannot advance even though rule 1 would permit it. Their subgroup peers must catch up first.

```python
global_min = min(paired_counts.values())

def is_eligible(t_id):
    if paired_counts[t_id] != global_min:
        return False                              # blocked by global check
    truck_mates = truck_to_trainers[trainer_to_truck[t_id]]
    truck_min = min(paired_counts[mate] for mate in truck_mates)
    return paired_counts[t_id] == truck_min      # blocked if ahead of truck-mate
```

Build the reverse map (`truck_to_trainers`) once before the loop — not inside it — to avoid O(n²) cost on large crews.

---

### Pre-pass interactions: count early placements before the round-robin runs

`run_dispatch` has a continuation pre-pass that places trainees with their continuation trainer before `assign_trainees` runs. This gives some trainers a head start of 1 before the round-robin begins.

The fix handles this correctly because `paired_counts` is computed from `assigned_crews` at the start of each iteration — it reflects whatever is already in the crew list, whether placed by the pre-pass or a prior round-robin iteration. A trainer with a pre-pass trainee will have count 1 and will be blocked by the intra-truck check until their truck-mates reach 1.

**Rule:** If a service runs after a pre-population step, count the pre-populated state as part of the initial distribution. Never assume a clean-slate count at the start of a sub-service call.

---

### Always add a defensive fallback, but do not rely on it

The two-level check has a theoretical edge case: if every trainer is ahead of their own truck-mates simultaneously (impossible in normal operation but logically possible with circular dependency), the eligible list is empty. An empty `eligible` passed to `random.choice` raises `IndexError`.

The fix includes a fallback that relaxes to global minimum only:

```python
if not eligible:
    eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == global_min]
```

This fallback should never fire. If it does, a log warning should be emitted so the condition can be investigated. **Do not silently swallow unexpected states** — the fallback is a safety net, not a normal code path.

---

## 2026-04-14 Authenticated API Client — Never Use Raw axios

### The mistake: importing axios directly in a page component

`AdminDashboard.tsx` was the only page that imported `axios` directly instead of `axiosClient`:

```typescript
import axios from 'axios';
const API = 'http://localhost:8000/api/v1';
axios.get(`${API}/employees/`)
```

Every other page uses `axiosClient`, which attaches the Cognito `idToken` as `Authorization: Bearer <token>` on every request. Raw `axios` has no interceptor — requests go out without a token.

The backend `RoleChecker` rejected every request with 401. The dashboard rendered completely empty with no error shown and no console warning, because `Promise.allSettled` absorbed all four failures silently.

**Rule:** `axiosClient` is the only permitted way to make API calls in this frontend. Never import `axios` directly in a page or component. The base URL and auth token are already handled — callers only need to provide the path.

---

### Why `Promise.allSettled` makes unauthenticated requests invisible

`Promise.allSettled` is the correct pattern for fan-out fetches: one failure should not block the others from completing. But it means every failure is silently swallowed unless you explicitly inspect each result's `.status` field.

This makes auth failures particularly dangerous. Instead of an error state or a rejected promise, the component receives nothing — state stays at its initial empty value, and the UI renders as if the server returned empty data. There is no visual signal of failure.

The fix eliminates the auth failure vector entirely (use `axiosClient`). But the lesson is broader: **when using `Promise.allSettled`, always log or surface settled rejections.** Silent failure is not the same as graceful degradation.

```typescript
const results = await Promise.allSettled([fetch1, fetch2, fetch3]);
results.forEach(r => {
  if (r.status === 'rejected') console.error('Fetch failed:', r.reason);
});
```

---

### The `include_inactive` pattern for admin-scoped list endpoints

The employee roster on the admin dashboard needs to show all employees — active and inactive — so the admin can see who has been deactivated and the workforce breakdown's "Inactive Employees" section can populate.

The `GET /employees/` endpoint previously hard-filtered `is_active == True` with no override. The fix mirrors the same `include_inactive: bool = False` pattern already on `GET /trucks/`:

- Default (`include_inactive=false`): all callers receive active-only — existing behaviour preserved.
- `include_inactive=true`: restricted to management/admin; returns all records regardless of active status.

**Rule:** When an endpoint needs to serve different scopes to different roles (active-only for field staff, all records for admin), add a query param with a safe default rather than duplicating the endpoint. Gate the elevated scope behind a role check inside the handler.

---

## 2026-04-14 Pagination Limits and Aggregate Counts

### Never derive aggregate counts from a paginated fetch

The admin Workforce Breakdown computed role counts by reducing the `employees` array returned from `GET /employees/`. The endpoint uses a default `limit=100`. With 193 employees, only the first 100 rows were returned — so the breakdown showed 1 trainee instead of 6.

The frontend had no way to know the list was truncated. There was no error, no warning, just wrong numbers.

**Rule:** If a UI element derives aggregate counts (totals, breakdowns, percentages) from a list, that list must be complete. Either fetch without a limit, raise the limit high enough to cover the realistic dataset, or use a dedicated summary endpoint. Never compute aggregates from a paginated slice.

In this codebase: workforce breakdown and KPI counters use `limit=500` on the employees fetch. The backend caps at 500, which comfortably covers the roster. If the roster ever exceeds 500, a dedicated `/employees/summary` endpoint returning pre-computed role counts is the right next step.

---

### Separate the fetch limit from the display limit

The fix for the truncated roster was:
1. Fetch all employees (`limit=500`) — needed for accurate counts
2. Display 50 at a time — needed to avoid an unusable 193-row table

These are independent concerns. The fetch limit is a data-correctness constraint. The display page size is a UX constraint. Conflating them (fetch 50, show 50) produces wrong counts. Separating them (fetch all, show 50) gives correct counts with manageable presentation.

**Pattern for client-side pagination:**
```typescript
// Fetch: get everything needed for counts and search
const allEmployees = await axiosClient.get('/employees/?limit=500');

// Derive: counts use the full array
const roleGroups = allEmployees.reduce(...);

// Display: slice for the current page
const pageSlice = allEmployees.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
```

Reset `page` to 0 whenever the filter or search changes — otherwise the user can be left on page 4 of a 1-result search.

---

## 2026-04-14 Role-Based Home Routing

### The mistake: a single `"/"` route for all roles

The Home navbar link and the `"/"` route both sent every authenticated user to the same `<Dashboard>` component. Admin users saw a generic multi-view widget. Dispatch users saw it too. Trainers and trainees had dedicated dashboards that required manual navigation to reach.

The implicit assumption was "authenticated means you belong on the dashboard." But the dashboard is a lowest-common-denominator view. Roles with dedicated pages should land on those pages.

**Rule:** When a role has a purpose-built home page, they should land there on login and when clicking Home — not on a generic fallback. "Authenticated" is not a sufficient criterion for where to send a user.

---

### Fix: `homeRoute` in the navbar + `RoleRedirect` at `"/"`

Two surfaces need updating — both the navbar link and the route itself:

```typescript
// Navbar: compute homeRoute from groups
const homeRoute = (() => {
  if (groups.includes('admin'))      return '/admin';
  if (groups.includes('dispatch'))   return '/dispatch';
  if (groups.includes('management')) return '/';
  if (groups.includes('trainer'))    return '/trainer-dashboard';
  if (groups.includes('trainee'))    return '/my-training';
  return '/';
})();

// App.tsx: redirect at "/" before rendering Dashboard
function RoleRedirect() {
  const { groups } = useAuth();
  if (groups.includes('admin'))    return <Navigate to="/admin" replace />;
  if (groups.includes('dispatch')) return <Navigate to="/dispatch" replace />;
  if (groups.includes('trainer'))  return <Navigate to="/trainer-dashboard" replace />;
  if (groups.includes('trainee'))  return <Navigate to="/my-training" replace />;
  return <Dashboard />;
}
```

Fixing only the navbar link is incomplete — users can navigate directly to `localhost:3000` or arrive there from a post-login redirect. `RoleRedirect` at the route level handles both cases.

Use `replace` on the `<Navigate>` so the browser history does not gain a `/` entry — the back button skips over the redirect rather than bouncing the user between `/` and their home page.

---

### A rich role-specific view is a page, not an embedded component

`ManagementView` was initially embedded inside `<Dashboard>` at `"/"`. It is a full operations dashboard — KPI row, incident trend, walker performance, training pipeline, fleet compliance. Despite its depth, it had no dedicated route and no page header of its own.

When management was given a dedicated `/management` route, the component needed promotion: add `useAuth` for the user's name, add a greeting header matching the pattern of other dashboards, register the route, and update `RoleRedirect` and `homeRoute` to point there.

**Rule:** If a component has enough content to constitute a user's primary work surface, it should be a standalone page with its own route and header — not a section inside a generic wrapper. The test: would a user bookmark this view directly? If yes, it is a page.

---

## 2026-04-15 Role Branching Within a Page and Self-Resolution via `/employees/me`

### When a page serves two roles with completely different purposes, branch at the top

`/field-ops` is granted to both `driver` and `admin`. Drivers use it as an action tool — check-in, inspection, departure, return, walker rating. Admin uses it as an analytics surface — read-only view of today's field activity across all drivers.

These two purposes share nothing. The correct pattern is a branch at the top of the page export:

```typescript
export default function FieldOps() {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  if (isAdmin) return <AdminFieldOpsView />;
  // ... driver flow below
}
```

`AdminFieldOpsView` has no knowledge of the driver panels and vice versa. Adding features to one branch never risks breaking the other.

**Rule:** When two roles share a route but have different purposes, branch immediately — don't add conditionals throughout a shared JSX tree. The branch point is the page component itself.

---

### Resolve the authenticated user's employee record with `/employees/me`, not a list search

The driver flow needed the caller's Employee DB ID. The original code fetched `GET /employees/` (active only, default limit 100) and searched for `discord_id === user.username`. This fails silently when:
- The employee is beyond the first 100 records in the default ordering
- The Cognito `username` doesn't match the stored `discord_id` format
- The employee is inactive

`GET /employees/me` resolves directly from the JWT's `sub` / `email` claims — one request, no search, no pagination risk:

```typescript
axiosClient.get('/employees/me').then(res => setEmployeeId(res.data.id))
```

**Rule:** Never resolve "who am I?" by fetching a list and searching it. Use a dedicated `/me` endpoint that the server resolves from the authenticated token. List searches are fragile under pagination and field-matching assumptions.

---

## 2026-04-15 Building Aggregate Analytics Views for Admin Roles

This section was written after replacing the admin's per-employee preference selector with a system-wide analytics view. The pattern applies any time you have a page that serves field staff in edit mode but should serve admin in analytics mode.

---

### Stale role-conditional code is a maintenance hazard

The original `Preferences` page had `isAdmin` sprinkled across six places:
- One `useEffect` gate
- One stale call inside `loadPreferences`
- One JSX block rendering an employee selector
- Three conditions on `canReassign`, `canFavBan`, and the trainee placeholder

When admin's purpose changed (from viewing individual records to viewing aggregates), each of these six spots became stale at different times, creating an inconsistent state where admin would early-return from effects but still render parts of the field-staff UI.

The fix was to move the role branch to a single point — the top of the component:

```typescript
const Preferences = () => {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  if (isAdmin) return <PreferenceAnalytics />;

  // field staff only below this line
  const isTrainee = groups.includes('trainee');
  ...
};
```

After the early return, every remaining `isAdmin` reference in the component is dead code and should be removed. TypeScript won't catch these — you have to do it manually.

**Rule:** Role branching belongs at the top of the component, not distributed through effects and JSX conditions. One branch point → one cleanup location → no stale guards.

---

### `useMemo` for derived analytics data

Preference analytics derives multiple computed values from the same two raw lists (relationships + employees):

- `empMap` — id-keyed lookup (used by every other derived value)
- `favs` / `bans` — filtered lists
- `mutualBans` — set intersection
- `matrix` — 3×3 role counts
- `matrixMax` — normalizer for color intensity
- `favCounts` / `banCounts` — top-10 sorted aggregates

Without `useMemo`, every one of these recomputes on every render — including renders triggered by expand/collapse toggles that have nothing to do with the data.

Wrap each in `useMemo` with its actual dependencies. The dependency list documents what each value depends on:

```typescript
const empMap = useMemo(() => Object.fromEntries(emps.map(e => [e.id, e])), [emps]);
const favs   = useMemo(() => rels.filter(r => r.relationship_type === 'fav'), [rels]);
const matrix = useMemo(() => { ... }, [rels, empMap]);     // depends on both
const matrixMax = useMemo(() => { ... }, [matrix, matrixTab]); // depends on which tab
```

**Rule:** Derived analytics values should always be memoized. The dependency list is also documentation — it tells you what re-triggers each computation.

---

### Relative color intensity, not absolute thresholds

The role interaction matrix uses heat-map coloring to make the dominant patterns visible at a glance. The naive approach is to pick thresholds: "0–5 = light, 6–15 = medium, 16+ = dark." This breaks the moment the data doesn't fit those ranges.

The correct approach is relative intensity:

```typescript
const intensity = val / matrixMax;
const bg = `rgba(34,197,94,${intensity * 0.35})`;
```

`matrixMax` is the largest value in the current tab (favs or bans). Every other cell is colored proportionally. A dataset with max=3 and a dataset with max=300 both produce a visible gradient — the darkest cell is always clearly darkest.

**Rule:** Heatmap coloring should be relative to the dataset maximum, not absolute. Hard-coded thresholds require ongoing calibration as data grows.

---

### Mutual ban detection via set membership (O(n), not O(n²))

Finding mutual bans — pairs where A bans B *and* B bans A — could be done with a nested loop over the ban list. That's O(n²) and runs on every render.

The efficient approach:

1. Build a `Set` of all ban pairs as `"employeeId:targetId"` strings — O(n)
2. Iterate the ban list once, check `banSet.has(reverse)` — O(1) per lookup
3. Track seen pairs with a sorted key to avoid duplicates

```typescript
const banSet = new Set(bans.map(r => `${r.employee_id}:${r.target_employee_id}`));
const seen = new Set<string>();
const pairs: { a: string; b: string }[] = [];
for (const r of bans) {
  const reverse = `${r.target_employee_id}:${r.employee_id}`;
  const key = [r.employee_id, r.target_employee_id].sort().join(':');
  if (banSet.has(reverse) && !seen.has(key)) {
    seen.add(key);
    pairs.push({ a: r.employee_id, b: r.target_employee_id });
  }
}
```

Total: O(n). The sorted key (`[a, b].sort().join(':')`) ensures the pair `(A,B)` and `(B,A)` both map to the same dedup string.

**Rule:** Intersection problems (does X also appear in set Y?) are O(1) per lookup with a Set. Don't use nested loops for membership checks.

---

## 2026-04-15 Designing Consolidated Management Views

This section was written after consolidating management's schedule oversight from two separate pages into one unified `ScheduleManagementView` component on the `/schedule` route.

---

### The "same route, different purpose" pattern applies to management too

When a route's purpose differs completely between two role groups, branch immediately at the component level. This is true even when the roles seem related.

Management and field staff both have a legitimate interest in `/schedule`, but for opposite reasons:
- Field staff: "What am I assigned to? Can I request PTO?"
- Management: "What requests are pending? Who is available next week?"

Putting both views in one component, gated by `isPrivileged` flags scattered through JSX, means every change to the management view risks touching field-staff rendering logic. Branching early prevents this:

```typescript
if (isPrivileged) return <ScheduleManagementView isAdmin={isAdmin} />;
// field staff view below — completely isolated
```

**Rule:** When two role groups visit the same route for fundamentally different reasons, branch at the top of the component. Don't add `{isPrivileged && (...)}` blocks inside a shared JSX tree.

---

### Unified queues need triage tools built in

The original approval queue was a flat 2-column grid of all pending request types. It had no sort order, no filter, and no indication of how long each request had been waiting. A manager scanning 15 pending items had no way to identify the most urgent without reading every card.

A useful approval queue has three things:

1. **Type filter** — switch between All / PTO / Workday / Rework. Allows focused review of one category at a time.
2. **Sort order** — "Oldest first" surfaces requests that have been waiting longest. This is the de facto SLA enforcement mechanism without needing formal SLA tooling.
3. **Age badge** — makes the wait time visible without requiring the reviewer to do date math:

```typescript
const daysSince = (isoStr: string) => Math.floor((Date.now() - new Date(isoStr).getTime()) / 86_400_000);

// Color-coded: neutral < 3d, yellow 3–6d, red ≥7d
const cls = days >= 7 ? 'bg-danger/10 text-danger'
  : days >= 3 ? 'bg-warning/10 text-warning'
  : 'bg-accent text-muted-foreground';
```

**Rule:** Any approval queue that can accumulate items needs: type filtering, age visibility, and oldest-first sort. Without these, the oldest items sink to the bottom and get missed.

---

### Use parallel requests for day-by-day aggregation when no summary endpoint exists

The 4-week availability heatmap needed availability data for 28 consecutive days. The existing endpoint was `GET /schedule/available/{date}` — one call per day.

Two options:
1. Add a backend endpoint `GET /schedule/availability-summary?start=...&end=...` that returns all 28 days in one response
2. Fire 28 parallel requests in the frontend

Option 1 is correct at scale. Option 2 is acceptable when:
- The endpoint is cheap (a simple DB query per date)
- The number of calls is bounded and small (28 is reasonable; 365 is not)
- A new backend endpoint would add complexity that isn't yet justified

```typescript
Promise.allSettled(
  dates.map(dt =>
    axiosClient.get(`/schedule/available/${dt}`).then(r => ({ dt, data: r.data }))
  )
).then(results => {
  const map: Record<string, {...}> = {};
  for (const res of results) {
    if (res.status === 'fulfilled') map[res.value.dt] = summarize(res.value.data);
  }
  setHeatmapData(map);
});
```

`Promise.allSettled` ensures partial failures (a single date returning 500) don't blank the entire heatmap — the other 27 days still render.

**Rule:** Parallel requests with `Promise.allSettled` are an acceptable substitute for a summary endpoint when the call count is small and bounded. Document the threshold in the ADR so future maintainers know when to add the endpoint instead.

---

### Route access flags need to be updated in both the route config and the navbar

Every route has two access controls:
1. The `allowedRoles` array on the `<ProtectedRoute>` in `App.tsx` — determines whether navigation to the URL succeeds
2. The visibility condition on the `<NavLink>` in `Navbar.tsx` — determines whether the link appears in the navigation

These must stay in sync. Adding a role to `allowedRoles` without updating the navbar means the role can navigate directly to the URL but won't see the link. Updating the navbar without updating `allowedRoles` means the link appears but clicking it produces an "Access Denied" page.

When you add a role to a route, update both surfaces in the same commit.

```typescript
// App.tsx
<Route path="/schedule" element={
  <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management', 'admin']}>
    <Schedule />
  </ProtectedRoute>
} />

// Navbar.tsx
const canAccessSchedule = isFieldStaff || groups.includes('management') || groups.includes('admin');
```

**Rule:** Route access is a two-surface change: `allowedRoles` in the route config AND the visibility flag in the navbar. Never update one without the other.

---

## 2026-04-15 Designing Drill-Down Pages for Aggregate Dashboard Cards

This section was written after building the Vehicle Compliance page in response to the management dashboard's "Vehicle Compliance (7d)" card being uninterpretable.

---

### Aggregate metrics without explanation read as per-record facts

The original card showed: **"Brakes — 3 failures, 15% fail rate"**.

A manager reads this as: "There is a truck with brake problems." What it actually means is: "Of all pre-trip inspections submitted fleet-wide in the last 7 days, 3 of them marked brakes as failed." The "15% fail rate" is the percentage of all inspections — not the percentage of trucks that have brake issues.

Aggregate summaries are useful (they surface patterns invisible in individual records), but they must be labeled as aggregates. Add an explanatory sentence wherever an aggregate number is displayed that could be misread as a per-entity fact:

```tsx
<p className="text-xs text-subtle mb-4">
  How many inspections flagged each item as failed across all drivers and trucks this week.
  A high fail rate signals a recurring mechanical issue — visit{' '}
  <a href="/vehicle-compliance">Vehicle Compliance</a> to see which trucks and drivers are responsible.
</p>
```

**Rule:** Every aggregate metric on a dashboard card needs one sentence explaining what the unit of measurement is. If a number could be misread as a per-entity count, it probably will be.

---

### Dashboard cards should link to their drill-down page

A dashboard is a summary surface. When a card shows something actionable (a high failure rate, an escalated trainee, an unresolved incident), the manager's next step is to investigate. If there's no clear path from the card to the detail view, they have to navigate manually or won't follow up at all.

Every dashboard card that summarizes something with a dedicated page should end with a link:

```tsx
<a href="/vehicle-compliance" className="block text-center text-xs text-primary hover:underline pt-4">
  View full compliance report →
</a>
```

This is a one-liner that dramatically improves discoverability. Apply it retroactively to existing cards (Incidents → `/incidents`, Training Pipeline → `/trainee-management`, etc.).

**Rule:** Dashboard cards are entry points, not endpoints. Always include a "View all →" or "Full report →" link to the detail page.

---

### The heatmap axis toggle resolves two conflicting analysis needs

The Vehicle Compliance heatmap answers two different questions:
1. **Which truck keeps failing brakes?** → need item × truck axis
2. **Which driver keeps submitting failed inspections?** → need item × driver axis

Both are valid. Building separate tables for each wastes space. A tab toggle with two states (`by truck` / `by driver`) lets the same heatmap answer both:

```tsx
const [axis, setAxis] = useState<'truck' | 'driver'>('truck');
// ... matrix is re-derived from useMemo([failed, axis])
```

The toggle costs two lines of state and one extra `useMemo` dep. The alternative — two full heatmap tables always rendered — doubles the DOM and makes the page harder to read.

**Rule:** When a visualization answers two related but distinct questions by changing one axis, implement a toggle rather than two separate sections. Keep the toggle state as minimal state (`useState`), derived data as `useMemo`.

---

### Client-side filtering is correct when the full dataset is already fetched

The history table filter (by driver, truck, pass/fail) runs entirely in the browser against the already-fetched dataset. This is the right choice when:

1. The dataset was already fetched in full for other purposes (KPIs, heatmap)
2. The record count is small enough to hold in memory (hundreds, not tens of thousands)
3. Filter changes should feel instant (no loading states)

The alternative — server-side filtering via query params — is correct when:
1. The dataset is too large to fetch in full
2. Only a small fraction of records will ever be viewed
3. The page only shows filtered results, not aggregates derived from the full set

In this case, the KPIs and heatmap need the complete unfiltered dataset anyway, so fetching filtered subsets per filter change would waste both — you'd need to maintain two fetches (full for aggregates, filtered for table). Fetch once, filter in memory.

**Rule:** Client-side filtering is correct when the full dataset is already in memory for other computations. Only move to server-side filtering when the dataset size makes the full fetch impractical. Document the threshold.

---

## 2026-04-15 Building Performance Grading Systems

This section was written after adding all-time letter grades, a leaderboard, and a per-walker profile panel to the walker performance view.

---

### Letter grades give management a normalised signal; raw numbers do not

A dashboard card showing "84% presence, 3.7 ★" requires the viewer to do interpretation work: Is 84% good? Is 3.7 out of 5 acceptable? How does this compare to other walkers?

A letter grade collapses that interpretation into one character that is immediately actionable:
- A/B = this person is performing well, no action needed
- C = worth watching, check the trend
- D/F = escalate, start a performance conversation

The grade is computed once on the backend from a stable formula, so management always sees the same signal regardless of how they access the data (dashboard card vs full page).

```python
def grade(presence_rate, avg_stars):
    p = (presence_rate or 0) / 100
    s = (avg_stars or 0) / 5.0
    combined = p * 0.5 + s * 0.5
    if combined >= 0.90: return "A"
    if combined >= 0.75: return "B"
    if combined >= 0.60: return "C"
    if combined >= 0.45: return "D"
    return "F"
```

**Rule:** When a summary metric has multiple dimensions (presence + quality), compute a single normalised score on the backend. Expose the raw dimensions alongside it, but lead with the grade. Viewers should not have to do math.

---

### Fixed thresholds outperform percentile rankings for absolute quality signals

An alternative grading approach is to rank by percentile: top 20% = A, next 20% = B, etc. This feels objective but has a critical flaw: if the entire fleet performs badly, the top performer still earns an A. The grade becomes meaningless as an absolute quality signal.

Fixed thresholds (A ≥ 90%, B ≥ 75%, etc.) mean a C-grade is a C-grade regardless of who else is on the team. This is the correct choice when the grade is used to trigger performance action rather than just to rank people relative to each other.

**Rule:** Use fixed thresholds for grades when the grade is an absolute quality signal. Use percentile ranking only when the purpose is purely relative comparison (e.g., "who is the top performer this week?").

---

### Trend detection requires splitting the history, not comparing to a static baseline

The wallet profile panel shows whether a walker is Improving, Stable, or Declining. The naive approach is to compare this week's average to their all-time average — but this is meaningless if their all-time history is three weeks old.

The correct approach splits the full rating history in half chronologically, compares the first half (older) to the second half (more recent), and interprets the direction:

```typescript
const recent = rated.slice(0, Math.ceil(rated.length / 2));  // newer
const older  = rated.slice(Math.ceil(rated.length / 2));      // older
const diff = recentAvg - olderAvg;
if (Math.abs(diff) < 0.2) return 'stable';
return diff > 0 ? 'up' : 'down';
```

The 0.2-star threshold filters out noise — small fluctuations aren't meaningful trends. Require a minimum sample (≥4 rated shifts) before showing a trend at all.

**Rule:** Trend detection should split history into time buckets and compare them, not compare to a global average. Apply a noise threshold to avoid flagging small fluctuations as meaningful trends.

---

### Slide-in panels are better than modals for record detail

When a user clicks a row in a table to see detail, the two common approaches are:

1. **Modal** — a floating dialog centred on screen, usually with a dark overlay
2. **Slide-in panel** — a fixed drawer that appears from the right, occupying a partial-width side panel

Modals are correct for confirmations and short forms. They're wrong for detail views because:
- The overlay blocks the table behind — the user loses context about where they are
- Modals don't scroll well when content is long (rating history can be many entries)
- Modals feel disruptive for browse-and-review workflows

A slide-in panel keeps the table partially visible, has natural vertical scroll, and visually signals "you're looking at a detail of the thing you clicked" without a full-page navigation:

```tsx
// Panel anchored to the right edge, full height
<div className="fixed inset-0 z-50 flex justify-end">
  <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
  <div className="relative w-full max-w-lg bg-card border-l border-border shadow-2xl flex flex-col overflow-hidden">
    {/* content */}
  </div>
</div>
```

**Rule:** Use slide-in panels for record detail views, not modals. Modals are for confirmations and short forms. Panels are for browsing detail within a list context.

---

## Statistical Defensibility: Minimum Sample Thresholds

When computing aggregate metrics (grades, scores, ratings), a small sample size produces a misleadingly precise result. One shift with 5 stars = A grade, but that A means nothing.

The pattern: **gate the metric behind a minimum sample threshold, return `null` otherwise, and surface the reason in the UI.**

```python
# Backend: accept threshold as query param, mark eligibility in response
@router.get("/walker-leaderboard")
def get_walker_leaderboard(min_shifts: int = Query(1, ge=1)):
    ...
    grade_eligible = total_shifts >= min_shifts
    return {
        "grade": compute_grade(...) if grade_eligible else None,
        "grade_eligible": grade_eligible,
        ...
    }
```

```tsx
// Frontend: explain ungraded state contextually, not generically
{!w.grade_eligible && (
  <span className="text-xs text-subtle italic">({w.total_shifts} shifts)</span>
)}

// Info banner so users understand why some rows are blank
{ungraded.length > 0 && (
  <div className="...">
    {ungraded.length} walkers below the {minShifts}-shift threshold — adjust the threshold to include them.
  </div>
)}
```

**Rule:** Never display a metric that will mislead. Return `null` + a reason flag from the API. Explain the gap in the UI rather than hiding it or showing a confusing value.

---

## Filtering Without Touching KPIs

When a panel shows both summary statistics (KPIs) and a detail list, filtering should apply to the list only. Filtering the KPIs creates an inconsistency: the "Grade B" badge in the header would change to "Grade A" if you filtered to a good month, even though the canonical grade is B.

**Pattern:** always compute KPIs from the full dataset; apply filters only to the records list.

```python
# Backend: full history for KPIs, filter only the ratings list
all_rows = db.query(WalkerRating).filter(...).all()
filtered = [r for r in all_rows if r.date >= start_date]  # only for the list

total = len(all_rows)          # KPI: all-time
avg_stars = compute(all_rows)  # KPI: all-time
return { ..., "ratings": serialize(filtered) }  # list: filtered
```

**Rule:** KPIs are all-time unless the page is explicitly a "period report." Filters narrow what you browse, not what the aggregate says.

---

## Client-Side CSV Export

For datasets already fetched into the frontend, a server-side export endpoint is unnecessary overhead. Construct the CSV in the browser and trigger a download:

```tsx
function exportToCSV(rows: Row[]) {
  const headers = ['Name', 'Grade', 'Avg Stars'];
  const data = rows.map(r => [r.name, r.grade ?? '', r.avg_stars?.toFixed(2) ?? '']);
  const csv = [headers, ...data]
    .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `export-${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);  // clean up immediately
}
```

Export the `visible` (filtered + sorted) array, not `walkers`. This way the export respects whatever filter the user has applied. The file name always includes today's date for traceability.

**Rule:** Client-side CSV from already-loaded data is simpler and faster than a server endpoint. Only add a server export endpoint when data is paginated or too large to load all at once.

---

## Detecting Outliers: Deviation From Mean

When a metric comes from multiple sources (different drivers rating the same walker), the *variance* tells you whether to trust the mean. A walker with a 3.5 avg from ten drivers who all gave 3–4 is very different from a 3.5 avg where one driver gave 5 and another gave 2.

**Pattern:** compute per-source avg, compare to the overall mean, flag sources whose deviation exceeds a threshold:

```python
# Group by source
from collections import defaultdict
buckets = defaultdict(list)
for row in rows:
    buckets[row.driver_id].append(row.stars)

overall_avg = sum(all_stars) / len(all_stars)
FLAG_THRESHOLD = 1.0

for driver_id, stars in buckets.items():
    avg = sum(stars) / len(stars)
    deviation = avg - overall_avg
    flagged = abs(deviation) >= FLAG_THRESHOLD
```

**Threshold choice:** On a 1–5 scale, 1.0 star = 20% of the full range. It's large enough to filter noise while still catching meaningful divergence. Return the threshold value in the API response so the frontend can display it without hardcoding it.

**Rule:** Don't just surface the aggregate — surface its reliability. Flag sources that deviate significantly, and explain in the UI that this may indicate bias rather than actual quality variation.

---

## Security: Never Trust Client-Supplied Identity

Any field in a request body or query param that identifies "who is doing this" is a forgery vector. The pattern to eliminate it:

```python
# WRONG — client supplies their own identity
@router.post("/incidents/")
def submit_incident(payload: IncidentCreate, db=Depends(get_db)):
    reporter = db.query(Employee).filter(Employee.id == payload.reporter_id).first()

# RIGHT — server resolves identity from the JWT
@router.post("/incidents/")
def submit_incident(payload: IncidentCreate, reporter: Employee = Depends(get_caller_employee)):
    # reporter is the authenticated caller — not forgeable
```

Same pattern applies to query params:

```python
# WRONG — any caller can read any employee's data
@router.get("/incidents/my")
def get_my_incidents(reporter_id: UUID = Query(...), ...):
    q = q.filter(Incident.reporter_id == reporter_id)

# RIGHT — caller can only see their own
@router.get("/incidents/my")
def get_my_incidents(caller: Employee = Depends(get_caller_employee), ...):
    q = q.filter(Incident.reporter_id == caller.id)
```

**Rule:** If you find yourself accepting an ID that identifies the caller, replace it with `get_caller_employee`. The only IDs a request body should supply are IDs of *other* records (e.g., which truck, which walker) — never the caller's own identity.

---

## Security: Validate at the Schema Boundary

File upload size caps, format checks, and enum validation belong in Pydantic validators — not in route handlers, not in models. They run before the DB is touched and produce clean 422 responses.

```python
from pydantic import field_validator

_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB

class IncidentCreate(BaseModel):
    photo_url: Optional[str] = None

    @field_validator("photo_url")
    @classmethod
    def check_photo_size(cls, v):
        if v is not None and len(v.encode("utf-8")) > _MAX_PHOTO_BYTES:
            raise ValueError("photo_url exceeds the 5 MB size limit.")
        return v
```

**Rule:** Any constraint on input data that can be expressed as a Pydantic validator should be. Schema-layer validation is automatic, self-documenting, and returns structured errors without touching the DB.

---

## Security: Use `get_caller_employee` for All Reviewer/Auditor Attribution

Whenever an endpoint needs to record *who performed an action* (approved, rejected, resolved), use `get_caller_employee` rather than looking up the employee manually:

```python
# WRONG — fragile; only works for Discord-linked accounts
reviewer = db.query(Employee).filter(
    Employee.discord_id == current_user.get("username", "")
).first()
req.reviewed_by = reviewer.id if reviewer else None  # None when lookup fails

# RIGHT — handles all account types, always non-None or raises 403
@router.patch("/{id}/approve")
def approve(reviewer: Employee = Depends(get_caller_employee), ...):
    req.reviewed_by = reviewer.id  # always set correctly
```

`get_caller_employee` implements a four-step lookup chain (cognito_sub → discord_id → email → UUID) and permanently stamps `cognito_sub` for future fast-path lookups. Never replicate this logic manually.

---

## Security: JWKS Cache — Handle Key Rotation with a Single Retry

AWS Cognito signing keys rotate periodically. A cache that never refreshes will fail on new tokens after a rotation until the service restarts. The correct pattern: refresh once on a `kid` miss.

```python
_jwks_cache: dict[str, dict] = {}  # kid → key mapping

def verify_token(token):
    kid = jwt.get_unverified_header(token)["kid"]
    jwks = get_jwks()
    key = jwks.get(kid)
    if not key:
        # Possible key rotation — re-fetch once
        _jwks_cache.update(_fetch_jwks())
        key = _jwks_cache.get(kid)
    if not key:
        raise HTTPException(401, "Public key not found.")
    # ... decode with key
```

One retry distinguishes rotation (new kid appears after re-fetch) from forgery (kid still absent). Two retries could mask forgery; zero retries means rotation requires a restart.

---

## 2026-04-16 Bot Architecture: One Process, Multiple Cogs

### Build one bot with a Cog structure, not multiple bots

Discord's operational model is one bot per server. Multiple bots mean multiple identities, multiple permission sets, and employees needing to know which bot handles which command. The correct pattern is one bot process with feature areas split into Cogs — self-contained modules each responsible for one domain.

```
bot/
├── main.py              # bot init, loads cogs, webhook server
├── cogs/
│   ├── dispatch.py      # Phase 1 — publish, DMs, confirmations
│   ├── schedule.py      # Phase 2 — /schedule command
│   └── eta.py           # Phase 2 — ETA posting
└── services/
    └── api_client.py    # shared HTTP client, used by all cogs
```

**Rule:** Start with the Cog structure from day one, even if you only have one Cog. Adding a second feature to a flat `bot.py` requires a refactor. Adding a second Cog to a Cog-structured bot requires adding one file.

### Use Redis for ephemeral operational state, not PostgreSQL

Confirmation state (pending/confirmed/declined per employee per day) has three properties that make Redis the right choice over PostgreSQL:

1. **It's ephemeral** — today's confirmations are irrelevant tomorrow
2. **It doesn't need to be joined** — no SQL queries reference it
3. **It needs automatic expiry** — a 48-hour TTL handles cleanup without a scheduled job

```python
# Key pattern: dispatch:confirmations:{YYYY-MM-DD}
# Value: hash of { employee_id: "pending" | "confirmed" | "declined" }
await r.hset(key, employee_id, status)
await r.expire(key, 48 * 60 * 60)
```

**Rule:** Before adding a new DB table, ask: is this data relational? Does it need to be queried with joins or aggregated in reports? If the answers are no, and the data has a natural expiry, Redis is the right store.

### Secure internal service-to-service calls with a shared secret

The backend calls the bot's internal webhook to trigger publishes. This is an internal Docker network call — but it should still be authenticated so the endpoint can't be triggered by anything that reaches port 8001.

The minimal pattern: both services read `INTERNAL_SECRET` from the environment. The caller adds it as a header; the receiver rejects requests without it.

```python
# Sender (backend)
headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "")}

# Receiver (bot)
secret = request.headers.get("X-Internal-Secret", "")
if secret != os.environ.get("INTERNAL_SECRET", ""):
    return web.Response(status=401)
```

**Rule:** Internal service calls on a private network are not inherently safe — a misconfigured proxy or compromised container could reach them. Always add a shared secret. The cost is two env var reads; the protection is significant.

### `timeout=None` on Discord button views for operational reliability

By default, `discord.ui.View` times out after 180 seconds and buttons stop responding. For operational buttons (confirm/decline an assignment) this is unacceptable — an employee might not see their DM for 10 minutes.

```python
class ConfirmationView(discord.ui.View):
    def __init__(self, ...):
        super().__init__(timeout=None)  # persists across bot restarts
```

Disable buttons after the first response so the employee can't change their answer. The view state is ephemeral — on bot restart, old views become non-functional, but the confirmation is already recorded in Redis.

**Rule:** Any Discord button that records a one-time operational response should use `timeout=None` and disable all buttons after the first interaction.

---

## 2026-04-16 Duplicate Entry Points Signal a Missing Consolidation Decision

### When two routes show the same content to the same role, one of them is wrong

Management had access to both `/schedule` and `/schedule-changes`. Both surfaced a schedule change request approval queue. `/schedule` did it better — it included a heatmap, age badges, PTO approvals alongside schedule change approvals, and type filtering. `/schedule-changes` for management was a subset with no additional value.

The root cause: the approval queue was built first on `/schedule-changes`, then the `/schedule` management view was built later and replicated it with improvements. The old entry point was never removed.

**Rule:** When a role has access to two routes that partially overlap, that is a signal that a consolidation decision was deferred, not made. Ask: does this role have a distinct purpose on each route, or are they doing the same thing in two places? If the same thing, remove the inferior entry point entirely — don't just make them equivalent.

### Absence from an allowlist is not always intentional

`dispatch` was missing from `/schedule-changes` `allowedRoles`. The route comment said "dispatch excluded — not their job." But dispatch employees are dispatched workers with a weekly schedule. They have exactly the same need to submit add/drop/rework requests as any driver or walker.

The exclusion was carried over from an earlier version of the route when dispatch's role was less clearly defined. By the time the role architecture was finalized, the exclusion was never revisited.

**Rule:** When adding or removing a role from a route, check every other route in the same domain for consistency. An exclusion that made sense at one phase of the project may be wrong after a later role architecture decision. Route access is not "set and forget."

---

## 2026-04-16 Complete the Loop: Submission Without Review is Half a Feature

### A data collection endpoint without a review surface is an incomplete feature

The feedback system had a modal for submitting feedback and a backend endpoint to store it. But there was no admin UI to read, triage, or act on submissions. Feedback went into the database and stayed there — invisible to anyone unless they queried the DB directly.

This is a pattern that appears in many systems: the submission path is built first (it's visible to users, it feels like progress), and the review surface is deferred as a "future task." But a feature that collects data with no one consuming it isn't a feature — it's a data sink.

**Rule:** Whenever a form submits data that a privileged user needs to act on, build the review surface in the same session. The submission endpoint and the inbox are one feature, not two. If you ship the form without the inbox, you have half a feature.

### Role scope should follow who has operational stake, not who has elevated access

`GET /feedback/` was gated to `management` + `admin`. Management was included by default, likely because they're an elevated role. But management's operational concern is scheduling, approvals, and crew oversight — not triaging bug reports or feature requests. They have no meaningful action to take on a piece of feedback.

The correct question is not "which roles are elevated?" but "which roles have operational stake in this data?" For feedback, the answer is admin (the developer/system owner) only.

**Rule:** When deciding which roles can access an endpoint, ask: which roles have a *reason* to act on this data? Elevated access level is not a sufficient reason on its own. Include only the roles with actual operational stake.

---

## 2026-04-16 Read From State, Not Hardcoded Fallbacks

### Event handlers should derive API payloads from loaded state, not constants

`handleDropToTruck` in `DispatchDashboard.tsx` sent `role: "walker"` hardcoded to the backend whenever an employee was dragged from the unassigned panel to a truck. The `availablePool` state map — which contains the full employee record including `role` — was already loaded and available in the same component. The data was there; the handler just didn't use it.

The consequence: any trainer, driver, or trainee dragged manually was stored in the DB with `role = "walker"`, creating a silent mismatch between the displayed role (sourced from `employees[id].role` in the UI) and the stored assignment role.

**Rule:** When a component renders data from a state map, that map is the correct source for values in event handlers that need to send data to an API. Never hardcode a value that could be read from already-loaded state. The only safe fallback is for genuine missing-data cases, not as a shortcut for data that's already available.

```typescript
// Wrong — hardcodes role regardless of who was dragged
role: "walker"

// Right — reads from the state map that drives the UI
const emp = availablePool[employeeId] || employees[employeeId];
const role = emp?.role || 'walker';
```

The `|| 'walker'` fallback is still present for defensive completeness (if neither map has the record, something else is already broken), but it should never fire in normal operation.

---

## 2026-04-16 Inverse Function Consistency

### Inverse functions share a contract — gaps in one are bugs by definition

`get_available_pool` and `get_unavailable_staff` are inverses: every employee in the available pool should be absent from the unavailable list, and every excluded employee should appear in the unavailable list with a reason. They implement the same exclusion logic from opposite directions.

The bug: `get_available_pool` excluded employees with approved recurring off-days but not employees with approved PTO requests. `get_unavailable_staff` excluded both. An employee with approved PTO for a given date appeared in the dispatch pool and could be assigned to a truck on their day off.

The functions were written at different points in time. Their exclusion logic was never cross-checked. The PTO filter was added to `get_unavailable_staff` correctly and simply never backported to `get_available_pool`.

**Rule:** When two functions are inverses of each other, treat their exclusion logic as a shared contract. Any exclusion criterion in one must exist in the other. Review both functions together whenever either is modified.

### The `~or_(...)` pattern for multi-condition SQLAlchemy exclusions

When a query must exclude rows matching any of several independent conditions, the cleanest SQLAlchemy pattern is:

```python
~or_(condition_a, condition_b)
```

Each condition is a separate EXISTS subquery (or scalar expression). SQLAlchemy compiles both into the same SQL query — one round-trip, no Python-level filtering needed. This is preferable to:
- Chaining multiple `~condition` filters (which produces `NOT A AND NOT B` — correct but less readable than `NOT (A OR B)`)
- Fetching the exclusion set in Python and filtering in memory (an extra round-trip)
- Using a LEFT JOIN with NULL filter (equivalent but harder to read for exclusion patterns)

---

## Security: Remove Hardcoded Credentials From Source Code

Config defaults that contain credentials get committed to source control and used silently in production if the env var is missing:

```python
# WRONG — credential in source code, silently used if DATABASE_URL not set
database_url: str = "postgresql://user:password@host/db"

# RIGHT — no default; missing env var causes loud startup failure
database_url: str  # required; set in .env
```

The credential belongs in `.env` (gitignored), not in `config.py` (tracked). A loud `ValidationError` at startup is always preferable to silently connecting to the wrong database.

---

## Testing: Add New Tables to DISPATCH_TABLES When Services Need Them

`conftest.py` uses a targeted `MetaData` (not `Base.metadata.create_all`) so SQLite doesn't try to compile PostgreSQL-specific columns. Every time a service is updated to query a new table, that table must be added to `DISPATCH_TABLES`:

```python
from app.models.time_off_request import TimeOffRequest

DISPATCH_TABLES = [
    ...
    TimeOffRequest.__table__,  # required when available_pool.py queries time_off_requests
]
```

Failing to do this causes `OperationalError: no such table: <name>` across the entire test suite. The error message is clear — the fix is always "import the model and add its `__table__` to the list."

---

## Testing: Use autouse=True for File-Wide Side Effect Patches

When every test in a file needs the same mock (e.g., patching a bot webhook call), use `autouse=True` on the fixture instead of patching per-test:

```python
@pytest.fixture(autouse=True)
def _no_dm(monkeypatch):
    monkeypatch.setattr(
        "app.services.graduate_trainees._send_graduation_dm",
        lambda *args, **kwargs: None,
    )
```

This prevents: (1) tests that forget the patch from making real HTTP calls, (2) test failures in CI where the bot isn't running, (3) accidental Discord noise during local runs. The `autouse=True` approach is preferable to per-test `@patch` when the side effect is always unwanted in the file.

---

## Testing: Use Get-or-Create for Unique-Constrained Rows

When multiple test helper calls might produce the same `(truck_id, date)` pair — and a `UNIQUE constraint` exists on that pair — the second INSERT fails. Use get-or-create:

```python
def make_past_assignment(db, truck, days_ago):
    target = date.today() - timedelta(days=days_ago)
    existing = db.query(TruckAssignment).filter_by(truck_id=truck.id, date=target).first()
    if existing:
        return existing
    ta = TruckAssignment(id=uuid.uuid4(), truck_id=truck.id, date=target)
    db.add(ta)
    db.commit()
    db.refresh(ta)
    return ta
```

This mirrors real-world semantics (multiple employees can ride the same truck on the same day) and keeps test helpers composable.

---

## Testing: Parameterize Time Delta Assertions With Helper Arguments

Analytics that compute median or percentile over time deltas need exact, predictable values. Instead of inserting raw timestamps and doing mental math:

```python
def make_confirmation(db, employee, status="confirmed", response_minutes=10):
    now = datetime.utcnow()
    c = DispatchConfirmation(
        ...
        created_at=now - timedelta(minutes=response_minutes),
        confirmed_at=now if status == "confirmed" else None,
    )
```

Then assertions read as: "median of [5, 10, 15] minutes is 10" — directly matching the `response_minutes` values passed in. No timestamp arithmetic needed in the test body.
