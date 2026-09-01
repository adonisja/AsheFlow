"""Report where employee roles and Cognito groups disagree (ADR-317 D1).

Scheduled rather than run at startup: FastAPI here has no lifespan hook, and
adding one for a single log line would put a Cognito round trip in the boot path
of every container restart. A daily check surfaces drift within a shift of it
appearing, which is the timescale that matters — the incident this came from was
a role nobody had grouped for weeks.

Never raises. A directory problem must not fail a task queue.
"""
import logging

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.role_directory.check_role_directory_drift")
def check_role_directory_drift() -> dict:
    """Compare roles in use against populated Cognito groups. Reports only."""
    from app.services.role_directory_check import log_role_directory

    db = SessionLocal()
    try:
        report = log_role_directory(
            db,
            pool_id=settings.aws_cognito_user_pool_id,
            region=settings.aws_region,
        )
        return report.as_dict()
    finally:
        db.close()
