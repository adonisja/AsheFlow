from fastapi import FastAPI, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app import models
from app.models.base import Base
from app.core.config import settings
from app.api.deps import require_configured
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

# Routers that require a fully-configured company before any request is served.
# registration and companies.company_admin_router are exempt:
#   - registration: employees register before the company may be configured
#   - company_admin_router: this IS the setup endpoint — must be reachable to complete setup
_configured = [Depends(require_configured)]

api_v1_router.include_router(employees.router,                dependencies=_configured)
api_v1_router.include_router(trucks.router,                   dependencies=_configured)
api_v1_router.include_router(truck_assignments.router,        dependencies=_configured)
api_v1_router.include_router(assignment_members.router,       dependencies=_configured)
api_v1_router.include_router(employee_off_days.router,        dependencies=_configured)
api_v1_router.include_router(employee_relationships.router,   dependencies=_configured)
api_v1_router.include_router(dispatch.router,                 dependencies=_configured)
api_v1_router.include_router(schedule.router,                 dependencies=_configured)
api_v1_router.include_router(time_off_requests.router,        dependencies=_configured)
api_v1_router.include_router(feedback.router,                 dependencies=_configured)
api_v1_router.include_router(training.router,                 dependencies=_configured)
api_v1_router.include_router(notifications.router,            dependencies=_configured)
api_v1_router.include_router(field_ops.router,                dependencies=_configured)
api_v1_router.include_router(continuation_requests.router,    dependencies=_configured)
api_v1_router.include_router(assignment_change_requests.router, dependencies=_configured)
api_v1_router.include_router(incidents.router,                dependencies=_configured)
api_v1_router.include_router(schedule_change_requests.router, dependencies=_configured)
api_v1_router.include_router(audit.router,                    dependencies=_configured)
api_v1_router.include_router(trainer_marks.router,            dependencies=_configured)
api_v1_router.include_router(trainer_coverage.router,         dependencies=_configured)
api_v1_router.include_router(anchor_points.router,            dependencies=_configured)
api_v1_router.include_router(analytics.router,                dependencies=_configured)
api_v1_router.include_router(shift_ops.router,                dependencies=_configured)
api_v1_router.include_router(companies.router,                dependencies=_configured)
# Exempt — must be reachable before and during setup
api_v1_router.include_router(registration.router)
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
