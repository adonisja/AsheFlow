# Engineering Journal: April 9, 2026 (PM Update)

## Seed Data, Role-Based Relationship Enforcement, and UI/UX Bug Fixes

### Feature/Architecture Updates
- Merged test user and seed user logic into a single, non-destructive seed script. Now, both test and sample users are created if missing, and trucks are preserved.
- The seed script and backend now strictly enforce that only drivers, trainers, and walkers can favorite or ban others. Management, admin, dispatch, and trainee roles are exempt from being favorited or banned.
- The frontend Preferences page now filters out exempt roles from the fav/ban selection lists, ensuring UI and backend are always in sync.
- Added robust error handling in the seed script for missing roles in FAV_LIMITS, preventing crashes when new roles are introduced.

### Bug Fixes
- Fixed parse errors in Schedule.tsx by moving function definitions outside JSX.
- Resolved ReferenceError in Preferences.tsx by unifying role variable names.
- Fixed 404 errors when creating relationships by ensuring test users are always present after seeding.
- Prevented destructive deletes in the seed script, preserving all users and trucks.
- Fixed PTO cancel logic and improved feedback for pending/cancelled PTO requests.
- Ensured impersonation dropdown is admin-only in both Preferences and Schedule pages.

### Lessons Learned
- Always keep backend and frontend role logic in sync to avoid silent business logic bugs.
- When expanding roles, update all enums, constraints, and UI logic together.
- Non-destructive seeding is critical for iterative development and testing.
- Filtering at both the API and UI layers prevents accidental privilege escalation or business rule violations.

---
# Engineering Journal: April 9, 2026

**Session Start Time**: 2026-04-09
**Session End Time**: 2026-04-09

## Goal for the Session
Introduce a new hierarchical employee role ("trainee") that requires specialized dispatch grouping. Trainees must be assigned immediately after trainers, prioritizing trucks with trainers to simulate a 1:1 pairing. Furthermore, after completing 5 successful assignments, a Trainee must automatically graduate to a "Walker" on their 6th dispatch. 
We also needed to ensure the UI sorts and groups employees uniformly within their respective crew blocks on the dashboard.

## Problems Encountered
* **UI Sorting and Grouping**: The frontend `DispatchDashboard.tsx` needed to visually group roles (Drivers vs Trainers vs Walkers) without breaking the draggable React components or duplicating them. We needed a centered label separator that reads `--- TRAINER ---`.
* **Backend Crash / Infinite Frontend Spin Illusion**: The dispatch page appeared to infinitely reload and trigger `500 Internal Server Errors`. Initial assumptions pointed towards a React `useEffect` infinite loop or a faulty state setter triggering re-renders. 
  * *Why?*: It turns out `uvicorn` (FastAPI's server watcher) crashed due to a missing closing bracket `})` in `app/services/run_dispatch.py` on line 73. This meant `GET /dispatch` or `POST /dispatch` was failing silently on the backend, creating a generic `ERR_FAILED 500`.
* **Check Constraint Trainee Rejection**: After fixing the syntax, inserting a new `trainee` dispatch explicitly failed with a `psycopg2.errors.CheckViolation` in PostgreSQL.
  * *Why?*: Even though schemas (`Literal["driver", "trainer", "trainee", "walker"]`), frontend maps, and ORM objects were updated to accept `"trainee"`, the `assignment_members` table in Postgres had a strict `CHECK CONSTRAINT` (`ck_assignment_members_role`) permanently enforcing only the original 3 roles. 

## Solutions & Procedures
* **React Grouping**: Implemented a `sortCrewMembers` helper mapping the primary employee roles with a numeric hierarchy (`roleOrder`). Inside the JSX map, we utilized `React.Fragment` to look behind at the previous element's role (`prevRole`). If different from `currentRole`, it injects a flexbox `justify-center` generic separator line.
* **Dispatch Script Fix**: Extracted the terminal logs, pinpointed the trailing string syntax bug, and used `sed` and `python` to inject the missing closing brace to allow FastAPI to reboot successfully.
* **Database Constraint Alteration**: Instead of recreating the table (which would drop data), we wrote an explicit Python utility script (`alter_db.py`) executing a raw SQLAlchemy text command to `DROP CONSTRAINT ck_assignment_members_role` and `ADD CONSTRAINT` including `'trainee'`. We also seeded the database with 4 mock trainees using another utility script (`add_trainees.py`).

## Key Takeaways
* **Always Check Database Constraints**: Changing a basic text list or Schema in FastAPI/Pydantic or SQLAlchemy forms the *application* layer constraint, but the RDBMS enforces the structural rules. Always execute `ALTER TABLE` raw queries or write a new Alembic migration when expanding finite string literal arrays.
* **Trust the Backend Logs over the Frontend Spinners**: A spinning React button and `500 Server Error` almost always means a server panic, not a client-side loop. We wasted time checking `DispatchDashboard.tsx` when we should have checked the docker container logs first.