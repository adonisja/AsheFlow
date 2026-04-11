# Daily Engineering Journal

**Date:** April 8, 2026
**Author:** AsheFlow Engineering (GitHub Copilot & Akkeem)
**Focus Area:** Alembic Migrations & Data Seeding Validation

## 1. Activities & Accomplishments

### Database Architecture & Migrations
- Successfully set up and wired Alembic into the FastAPI backend (MVP Gap #7).
- Wiped the existing Docker database volume (`docker-compose down -v`) to prevent conflicting duplicate table creations between older `Base.metadata.create_all()` and Alembic.
- Configured `alembic/env.py` to dynamically pull the `DATABASE_URL` from the application's `settings` class and passed the model `Base.metadata` as the target for autogeneration.
- Successfully generated the baseline migration script (`alembic revision --autogenerate`) that captured the 6 core models: `employees`, `trucks`, `employee_off_days`, `employee_relationships`, `truck_assignments`, and `assignment_members`.
- Applied the initial migration schema to the fresh Postgres container using `alembic upgrade head`.

### Data Seeding Compliance Check
- User requested a thorough review of the `seed.py` file to ensure all generated test data complied with the exact business rules defined in the architecture.
- Identified **one major compliance violation** against `ADR-001-Role-Based-Fav-List.md`: The seed data was allowing `drivers` to favorite up to 3 `walkers`. According to the ADR, the hard limit across the entire system for any role targeting a walker is 2.
- Automatically corrected the `FAV_LIMITS` dictionary in `seed.py` to strictly enforce the rule (`"driver": {"walker": 2}`).

## 2. Technical Decisions & Challenges

### Autogenerate Drift Detection
**Challenge:** Initially ran into an `ImportError` inside `alembic/env.py` caused by a mismatch in the model class name (`DayOff` vs `EmployeeOffDay`).
**Resolution:** Corrected the import statement to reflect the actual model class name (`EmployeeOffDay`). This highlights the exact reason why checking drift using autogenerate on a completely empty database is critical: it immediately exposes any disconnects between the codebase definition and the database connection layer.

### Seed Script Architecture
**Observation:** The seed script handles table clearing with a deliberate topological sort (children before parents: `EmployeeRelationship`, `EmployeeOffDay`, `AssignmentMember`, `TruckAssignment` before `Employee` and `Truck`) which safely avoids foreign key constraint violations during development resets.

## 3. Next Steps
- Implement MVP Gap #8: **API Versioning** (mounting all current routers under an `/api/v1/` prefix).
- Ensure all automated testing reflects the new v1 routes once API versioning is complete.
- Begin frontend/Discord bot client planning now that the backend database is stable and version-controlled.

## 4. Time Tracking
- **Session Duration:** ~45 minutes
- **Categories:** Database Administration (60%), Scripting/Compliance Review (40%)