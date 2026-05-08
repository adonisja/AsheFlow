from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app import models
from app.models.base import Base
from app.core.config import settings
from app.routers import employees, trucks, truck_assignments, assignment_members, employee_off_days, employee_relationships, dispatch, schedule, time_off_requests, feedback, training, notifications, field_ops, continuation_requests, assignment_change_requests, incidents, schedule_change_requests, audit, trainer_marks, trainer_coverage, anchor_points, analytics, shift_ops, registration, companies

# Alembic is now managing the database schema.
# We no longer need Base.metadata.create_all(bind=engine)

app = FastAPI(title="AsheFlow Dispatch API")

# Configure CORS — origins loaded from CORS_ORIGINS env var (comma-separated).
# Dev default is set in config.py; override with CORS_ORIGINS in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define our versioned API router
api_v1_router = APIRouter(prefix="/api/v1")

# Include all feature routers under the v1 prefix
api_v1_router.include_router(employees.router)
api_v1_router.include_router(trucks.router)
api_v1_router.include_router(truck_assignments.router)
api_v1_router.include_router(assignment_members.router)
api_v1_router.include_router(employee_off_days.router)
api_v1_router.include_router(employee_relationships.router)
api_v1_router.include_router(dispatch.router)
api_v1_router.include_router(schedule.router)
api_v1_router.include_router(time_off_requests.router)
api_v1_router.include_router(feedback.router)
api_v1_router.include_router(training.router)
api_v1_router.include_router(notifications.router)
api_v1_router.include_router(field_ops.router)
api_v1_router.include_router(continuation_requests.router)
api_v1_router.include_router(assignment_change_requests.router)
api_v1_router.include_router(incidents.router)
api_v1_router.include_router(schedule_change_requests.router)
api_v1_router.include_router(audit.router)
api_v1_router.include_router(trainer_marks.router)
api_v1_router.include_router(trainer_coverage.router)
api_v1_router.include_router(anchor_points.router)
api_v1_router.include_router(analytics.router)
api_v1_router.include_router(shift_ops.router)
api_v1_router.include_router(registration.router)
api_v1_router.include_router(companies.router)
api_v1_router.include_router(companies.company_admin_router)
# Mount the v1 router to the main app
app.include_router(api_v1_router)

@app.get("/health")
def health_check():
    """Return a simple liveness check response.

    Returns:
        A dict with key ``"status"`` set to ``"ok"``.
    """
    return {"status": "ok"}
