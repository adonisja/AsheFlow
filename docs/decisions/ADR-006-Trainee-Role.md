# Title: Lifeycle of the Trainee Role (ADR-006)

## Context
The dispatch logic originally separated field employees into three fixed roles: "driver", "trainer", and "walker". To handle newly onboarded staff and pair them with experienced leaders, the business required a new concept: the "Trainee". 

Constraints:
- Trainees must be grouped onto trucks that specifically possess a "Trainer" where possible.
- If a truck has no trainer, it should only be assigned a trainee as a last resort fallback.
- Trainees must autonomously transition into a "Walker" state after executing 5 discrete assignments to represent a graduation model.
- The UI mapping and Database check constraints must smoothly handle this 4th tier.

## Considered Options
* **Option 1**: Treat Trainees identically to Walkers but enforce a separate query prior to assignment, tracking their days manually using a separate "Days Worked" column on the Employee table.
* **Option 2**: Introduce "Trainee" as a new Core Role string literal throughout the application. Run a discrete algorithm phase (`assign_trainees`) right after `assign_trainers` but *before* `assign_walkers`, targeting priority trucks. Perform an automatic historical assignment count immediately before dispatch execution to graduate those with 5 previous logs.

## Trade-offs
**Option 1**: Adding a column strictly for `days_worked` adds stateful drift and creates another variable that can become out of sync with actual dispatch reality if someone is removed or reassigned manually.
**Option 2 (Chosen)**: By treating Trainee as a native role (`role = 'trainee'`), we allow the UI headers to sort them independently. Furthermore, generating `graduation_warnings` by dynamically `count()`ing the `AssignmentMember` table where `employee_id == trainee.id` creates a 100% accurate truth based strictly on *what actually happened* historically. As soon as the count hits `5`, the dispatch pipeline flips their Role property to "walker".

## Decision
We chose Option 2. We created `backend/app/services/assign_trainees.py` and `graduate_trainees.py` to handle the algorithms globally, woven directly into the core `run_dispatch.py` orchestration. This necessitated updating string Literals stack-wide and executing a direct Postgres `.execute("ALTER TABLE...")` statement to broaden the `ck_assignment_members_role` Check Constraint.

## Consequences
- **Positive**: Complete automated pairing and historical graduation (less manual tracking by the admin).
- **Negative (Tech Debt)**: Hardcoded literal typing (`"driver", "trainer", "trainee", "walker"`) spans UI `Record` objects, Pydantic framework validations, SQLAlchemy filters, and underlying Database constraints. Introducing a *fifth* role in the future will remain a high-touch process affecting the entire stack.

## Learnings & Growth
- Adding new enum-style entities requires a full-stack update (Frontend Sorting Maps -> FastAPI Pydantic -> Python Business Logic Arrays -> SQLAlchemy ORM definitions -> PostgreSQL raw Constraints). 
- Database check constraints are useful for data safety but will actively crash endpoints with `psycopg2.errors.CheckViolation` if the application layer expands enums without a corresponding `ALTER TABLE` schema update.