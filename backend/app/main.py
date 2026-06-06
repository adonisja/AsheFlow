import logging
import json
from fastapi import FastAPI, APIRouter, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.database import engine
from app import models
from app.models.base import Base
from app.core.config import settings
from app.api.deps import require_configured
from app.api.ratelimit import limiter
from app.routers import employees, trucks, truck_assignments, assignment_members, employee_off_days, employee_relationships, schedule, time_off_requests, feedback, notifications, continuation_requests, assignment_change_requests, incidents, schedule_change_requests, audit, trainer_marks, trainer_coverage, anchor_points, analytics, shift_ops, registration, companies, internal, shift_sessions, sort, location_profiles, location_profile_library, graduation_quiz, gear_requests, trainee_credentials, truck_transfers, driver_surveys

try:
    from asheflow_private.register import register_proprietary_routers as _register_proprietary
except ImportError:
    _register_proprietary = None


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record for CloudWatch Insights queries."""
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
            "time":    self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        })


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


_configure_logging()

# Alembic is now managing the database schema.
# We no longer need Base.metadata.create_all(bind=engine)

app = FastAPI(title="AsheFlow Dispatch API")

# SlowAPI — distributed rate limiting backed by Redis.
# Limits are defined per-endpoint in the routers; this wires the state and
# the 429 error handler into the FastAPI app.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Trust X-Forwarded-Proto from Caddy so redirect Location headers use https://.
# Caddy is the only trusted proxy — it runs in the same Docker network.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Configure CORS — origins loaded from CORS_ORIGINS env var (comma-separated).
# Dev default is set in config.py; override with CORS_ORIGINS in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=settings.get_cors_methods(),
    allow_headers=settings.get_cors_headers(),
    expose_headers=["X-Total-Count"],
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
api_v1_router.include_router(schedule.router,                 dependencies=_configured)
api_v1_router.include_router(time_off_requests.router,        dependencies=_configured)
api_v1_router.include_router(feedback.router,                 dependencies=_configured)
api_v1_router.include_router(notifications.router,            dependencies=_configured)
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
api_v1_router.include_router(shift_sessions.router,           dependencies=_configured)
if _register_proprietary:
    _register_proprietary(api_v1_router, _configured)
api_v1_router.include_router(sort.router,                     dependencies=_configured)
api_v1_router.include_router(location_profiles.router,        dependencies=_configured)
api_v1_router.include_router(location_profile_library.router, dependencies=_configured)
api_v1_router.include_router(graduation_quiz.router,          dependencies=_configured)
api_v1_router.include_router(gear_requests.router,            dependencies=_configured)
api_v1_router.include_router(trainee_credentials.router,      dependencies=_configured)
api_v1_router.include_router(truck_transfers.router,          dependencies=_configured)
api_v1_router.include_router(driver_surveys.router,           dependencies=_configured)
api_v1_router.include_router(companies.router,                dependencies=_configured)
# Exempt — must be reachable before and during setup
api_v1_router.include_router(registration.router)
api_v1_router.include_router(companies.company_admin_router)
# Bot-facing internal endpoints — authenticated by X-Internal-Secret, not Cognito
api_v1_router.include_router(internal.router)
# Mount the v1 router to the main app
app.include_router(api_v1_router)

@app.get("/health")
def health_check():
    """Return a simple liveness check response.

    Returns:
        A dict with key ``"status"`` set to ``"ok"``.
    """
    return {"status": "ok"}
