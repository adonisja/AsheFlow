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
