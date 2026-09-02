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
from app.api.deps import require_configured, RequireMode
from app.services.constants import MODE_FULL, MODE_WORKFORCE
from app.api.ratelimit import limiter
from app.routers import employees, trucks, truck_assignments, assignment_members, employee_off_days, employee_relationships, schedule, time_off_requests, feedback, notifications, continuation_requests, assignment_change_requests, incidents, schedule_change_requests, audit, trainer_marks, trainer_coverage, anchor_points, analytics, shift_ops, registration, companies, internal, shift_sessions, sort, graduation_quiz, gear_requests, trainee_credentials, truck_transfers, driver_surveys, adp, building_profiles, building_profile_library, walker_routes, rts, roll_call, crew_status, scorecards, scorecard_appeals, package_lookup, package_intake, dashboards, assignment_history, sort_metrics, btr_sheets, workforce_routes, manual_returns, company_zones, platform_alerts, crew_pins

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

# ADR-289: routers whose feature only exists when the tenant has an Amazon package
# feed. RequireMode returns 404 (not 403) — a company without a feed should not be
# told the endpoint exists. Keep this list in step with _FULL_MODE_FEATURES in
# routers/companies.py, which is what clients gate their navigation on.
_full_mode = _configured + [Depends(RequireMode(MODE_FULL))]

# ADR-291: the MIRROR of _full_mode. A tenant with a package feed sorts from the
# manifest and must not also have this weaker path available; a tenant without one
# has this and nothing else. Gating both directions is what keeps exactly one
# routing path reachable per company.
_workforce_mode = _configured + [Depends(RequireMode(MODE_WORKFORCE))]

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
# SSE stream router: NO _configured gate — that dependency reads the
# Authorization header, which EventSource cannot send. The stream auths via
# ?token= and enforces the configured-company check inline (see notifications.py).
api_v1_router.include_router(notifications.stream_router)
api_v1_router.include_router(continuation_requests.router,    dependencies=_configured)
api_v1_router.include_router(assignment_change_requests.router, dependencies=_configured)
api_v1_router.include_router(incidents.router,                dependencies=_configured)
api_v1_router.include_router(schedule_change_requests.router, dependencies=_configured)
api_v1_router.include_router(audit.router,                    dependencies=_configured)
api_v1_router.include_router(trainer_marks.router,            dependencies=_configured)
api_v1_router.include_router(trainer_coverage.router,         dependencies=_configured)
api_v1_router.include_router(anchor_points.router,            dependencies=_configured)
api_v1_router.include_router(analytics.router,                dependencies=_configured)
api_v1_router.include_router(assignment_history.router,        dependencies=_configured)
api_v1_router.include_router(shift_ops.router,                dependencies=_configured)
api_v1_router.include_router(shift_sessions.router,           dependencies=_configured)
# ADR-289: the proprietary bundle registers dispatch/training/field_ops itself and
# receives the base dependency list. Those three are THIN, not HIDE — their cores
# (crew pairing, training phases, inspections/fuel/check-in) have zero package
# coupling and must keep working in workforce mode — so they correctly stay on
# `_configured`. The package-coupled endpoints INSIDE them (dispatch's four
# package_manifest routes, field_ops' four walker-performance routes) need
# per-endpoint RequireMode(MODE_FULL) applied within asheflow_private, which this
# repo cannot do. `_full_mode` is passed so that bundle can gate them without
# reconstructing the dependency list and drifting from this one.
#
# The signature is INSPECTED, not tried/excepted: a bundle that accepts three
# arguments but raises TypeError from inside its own body would otherwise be
# registered a second time by the fallback, silently double-registering every
# proprietary route.
if _register_proprietary:
    import inspect as _inspect
    try:
        _accepts_mode = len(_inspect.signature(_register_proprietary).parameters) >= 3
    except (TypeError, ValueError):
        _accepts_mode = False   # C-implemented or unintrospectable — assume old form
    if _accepts_mode:
        _register_proprietary(api_v1_router, _configured, _full_mode)
    else:
        # Older bundle without the mode-aware signature — register unchanged rather
        # than failing startup. Its package endpoints stay ungated until it is updated.
        logging.getLogger(__name__).warning(
            "asheflow_private.register_proprietary_routers does not accept the "
            "full-mode dependency list (ADR-289); its package-coupled endpoints are "
            "NOT gated by operating_mode."
        )
        _register_proprietary(api_v1_router, _configured)
api_v1_router.include_router(sort.router,                     dependencies=_full_mode)
# ADR-312 — the operating zone is company configuration, not a sorting artifact.
# _configured, so a workforce tenant can define and read the area it delivers in;
# it was unreachable there only because the endpoints sat inside sort.py.
api_v1_router.include_router(company_zones.router,            dependencies=_configured)
api_v1_router.include_router(graduation_quiz.router,          dependencies=_configured)
api_v1_router.include_router(gear_requests.router,            dependencies=_configured)
api_v1_router.include_router(trainee_credentials.router,      dependencies=_configured)
api_v1_router.include_router(truck_transfers.router,          dependencies=_configured)
api_v1_router.include_router(driver_surveys.router,           dependencies=_configured)
api_v1_router.include_router(adp.router,                            dependencies=_configured)
api_v1_router.include_router(building_profiles.router,              dependencies=_configured)
api_v1_router.include_router(building_profile_library.router,       dependencies=_configured)
api_v1_router.include_router(walker_routes.router,                  dependencies=_full_mode)
api_v1_router.include_router(rts.router,                            dependencies=_full_mode)
api_v1_router.include_router(roll_call.router,                      dependencies=_configured)
api_v1_router.include_router(crew_status.router,                    dependencies=_configured)
api_v1_router.include_router(scorecards.router,                     dependencies=_configured)
api_v1_router.include_router(scorecard_appeals.router,              dependencies=_configured)
api_v1_router.include_router(package_lookup.router,                 dependencies=_full_mode)
api_v1_router.include_router(package_intake.router,                 dependencies=_full_mode)
# ADR-290 D1: MODE-INDEPENDENT — deliberately _configured, not _full_mode.
# In workforce mode this is the bag inventory the sort consumes; in full mode
# it is a dock-time reconciliation source against the manifest. Gating it would
# remove the reconciliation benefit from exactly the tenants who have a
# manifest to reconcile against.
api_v1_router.include_router(btr_sheets.router,                     dependencies=_configured)
api_v1_router.include_router(workforce_routes.router,               dependencies=_workforce_mode)
# ADR-292: the small workforce mirror of rts.py (which is _full_mode and carries
# 394 package references' worth of manifest coupling). Same models, same enum —
# only the manifest check is skipped and `source` records provenance.
api_v1_router.include_router(manual_returns.router,                 dependencies=_workforce_mode)
api_v1_router.include_router(dashboards.router,                     dependencies=_configured)
api_v1_router.include_router(sort_metrics.router,                    dependencies=_full_mode)
api_v1_router.include_router(companies.router,                      dependencies=_configured)
# Exempt — must be reachable before and during setup
api_v1_router.include_router(registration.router)
api_v1_router.include_router(companies.company_admin_router)
# ADR-335 — platform alerts are NOT mode- or setup-gated: an alert may have
# no owning tenant, and a super admin must be able to read them precisely
# when a company's configuration is broken.
api_v1_router.include_router(platform_alerts.router)
api_v1_router.include_router(crew_pins.router)
# Bot-facing internal endpoints — authenticated by X-Internal-Secret, not Cognito
api_v1_router.include_router(internal.router)
# Mount the v1 router to the main app
app.include_router(api_v1_router)

@app.get("/health")
def health_check(detail: bool = False):
    """Liveness check. `?detail=1` adds the role/Cognito agreement report.

    The detail is OPT-IN because /health is polled by infrastructure that only
    needs liveness, and because the report costs a Cognito round trip.

    It never changes the status: a directory problem affecting one role must not
    mark the API unhealthy for every correctly-grouped role (ADR-317 D1).
    """
    if not detail:
        return {"status": "ok"}

    from app.database import SessionLocal
    from app.services.role_directory_check import check_role_directory

    db = SessionLocal()
    try:
        report = check_role_directory(
            db,
            pool_id=settings.aws_cognito_user_pool_id,
            region=settings.aws_region,
        )
        # Names and counts only — never a username, email or sub (Dimension 6).
        return {"status": "ok", "role_directory": report.as_dict()}
    finally:
        db.close()
