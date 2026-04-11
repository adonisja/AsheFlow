# Journal Entry: April 8, 2026

## Schedule Viewer & Granular Time-Off Requests

### The Problem
During Phase 4 (Worker Endpoints), we finalized the worker `Preferences.tsx` tab. It handled Ban Lists, Favorite Lists, and Day-of-Week Off-Days. We successfully built a `Schedule.tsx` view that allowed workers to select their Employee Identity and visualize their upcoming 7-day schedule (including Truck assignments, crew mates, and off days).

However, during testing, two critical business logic failures surfaced:
1. **Cognito User Mapping vs Employee ID Mapping**: Initially, the backend expected the frontend to know the worker's `Employee.id`. The `AuthContext` only gives us their AWS Cognito `sub` ID and `email`. We bridged this gap temporarily by allowing the user to select an Employee via a `react-select` dropdown for demo/testing purposes. Eventually, this will need a rigid DB-to-Cognito mapping.
2. **Recurring Off Days vs Explicit Date Requests**: Our `EmployeeOffDay` model handled recurring days off (e.g. "I never work on Tuesday"). It did not support generic PTO ("I need May 14th off"). If a user tried to request a specific date off on the Calendar, it didn't align with the underlying database logic.

### The Solution
1. **New Database Layer**: I built a brand new SQLAlchemy model: `TimeOffRequest` specifically to handle explicit `Date` objects. 
2. **Double Constraints via Routers**: I exposed a new router `time_off_requests.py`. In the `POST` route, I added validation logic to check if the explicit date submitted (e.g. `2026-05-12`) fell on a day the user already had marked as an approved recurring off-day in the `EmployeeOffDay` table. If so, it raises an HTTP 400.
3. **Calendar Merging**: Modifying `schedule.py`, the API now pulls *both* the recurring week-off array, and the specific time-off array, layering them sequentially over the `assignment_map` so that `Specific Time Off` overrides `Recurring`, but `Assigned` overrides all (if Dispatch manually overrode it).
4. **UI**: Swapped native HTML `<select>` dropdowns to searchable `react-select` dropdowns because MacOS native menus break out of bounds when populated with 65+ seeded employees. Added a "Specific Request Time Off" section to `Preferences.tsx` with a native `<input type="date">`.

### Next Steps
We have successfully wrapped the core requirements for Phase 4. Roles are respected, Navbar links are protected, and workers can view their specific timelines based on dispatch history + PTO logic. Transitioning to Phase 5: The dynamic, grid-based Dispatcher Dashboard.