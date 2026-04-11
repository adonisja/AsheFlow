# 2026-04-09: Training Dashboard Backend Initialization

## Context
Following the creation of the `TRAINER_DASHBOARD_PLAN.md`, we began implementing the backend core required to support the 5-day trainee lifecycle logic.

## Changes Implemented
1. **Database Schema & Models (`backend/app/models/training.py`)**:
   - `TrainingCurriculum`: Tracks the templates for day-by-day training topics.
   - `TrainingRecord`: A stateful snapshot of the trainee's specific day under a specific trainer.
   - `TrainingTask`: Individual checklist items linked to the TrainingRecord, enabling completion tracking and "Training Debt" flags.
   - Initialized and correctly applied Alembic db migrations (`alembic revision --autogenerate` -> `alembic upgrade head`).

2. **API Schemas (`backend/app/schemas/training.py`)**:
   - Defined `TrainingRecordResponse` and `TrainingTaskResponse` for structured API replies.
   - Defined `ManagerCommentCreate` to handle incoming payloads for updating notes.

3. **API Endpoints (`backend/app/routers/training.py`)**:
   - `GET /api/v1/training/trainee/{trainee_id}`: Exposes chronological training logs and nested tasks. Includes RBAC restricting access to Managers and Trainers.
   - `POST /api/v1/training/trainee/{trainee_id}/manager-comments`: Provides an interface strictly for Managers (RBAC controlled) to add tasks or notes to a trainee's current record. Handles intelligent concatenation if a comment already physically exists for the given day (`\n\n[Added later]`).
   
4. **App Initialization (`backend/app/main.py`)**:
   - Imported and registered the new `training.router` with FastAPI's `api_v1_router`.

## Notes & Learnings
- Encountered several issues with the terminal environment (heredocs breaking/crashing). Moving forward, we should use pure python scripts or direct file operations (`create_file`) for multiline code injection to prevent character escapes and shell hanging. 
- Integrated custom `RoleChecker` directly into the router dependencies to explicitly define who uses `manager_comments` vs who views `trainne_history`.

## Next Steps
- Implement Curriculum Injection Logic: Hook into `run_dispatch.py` to auto-generate daily training records based on the curriculum.
- Build Immutability Logic: Lock records after the active assignment day.
- Build Manual Trainee Override Logic: Update the manual dispatch assignment endpoints to bump and replace fallback trainees properly.