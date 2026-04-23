"""Scheduled cleanup tasks for AsheFlow.

Registered in celery_app.py beat_schedule and executed by the Celery worker.
"""

import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal
from app.models.employee import Employee

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.cleanup.expire_pending_invites")
def expire_pending_invites() -> dict:
    """Delete employee records (and their Cognito users) that have been in
    ``pending_verification`` status for longer than ``INVITE_EXPIRY_DAYS`` days.

    Safe to run multiple times — only targets rows where:
    - account_status = 'pending_verification'
    - invited_at < now - INVITE_EXPIRY_DAYS

    Returns a summary dict with counts for observability.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.invite_expiry_days)
    db = SessionLocal()
    deleted_db = 0
    deleted_cognito = 0
    cognito_failures = []

    try:
        expired = (
            db.query(Employee)
            .filter(
                Employee.account_status == "pending_verification",
                Employee.invited_at < cutoff,
            )
            .all()
        )

        if not expired:
            logger.info("expire_pending_invites: no expired invites found.")
            return {"deleted_db": 0, "deleted_cognito": 0, "cognito_failures": []}

        cognito = boto3.client("cognito-idp", region_name=settings.aws_region)

        for employee in expired:
            # Delete from Cognito first — if this fails we still want to log it,
            # but we proceed with DB deletion so the record doesn't linger.
            if employee.email:
                try:
                    cognito.admin_delete_user(
                        UserPoolId=settings.aws_cognito_user_pool_id,
                        Username=employee.email,
                    )
                    deleted_cognito += 1
                except ClientError as e:
                    code = e.response["Error"]["Code"]
                    if code == "UserNotFoundException":
                        # Already gone from Cognito — treat as success
                        deleted_cognito += 1
                    else:
                        logger.error(
                            "Failed to delete Cognito user %s: %s", employee.email, e
                        )
                        cognito_failures.append(employee.email)

            db.delete(employee)
            deleted_db += 1

        db.commit()
        logger.info(
            "expire_pending_invites: deleted %d DB records, %d Cognito users. Failures: %s",
            deleted_db, deleted_cognito, cognito_failures,
        )

    except Exception as e:
        db.rollback()
        logger.error("expire_pending_invites task failed: %s", e)
        raise
    finally:
        db.close()

    return {
        "deleted_db": deleted_db,
        "deleted_cognito": deleted_cognito,
        "cognito_failures": cognito_failures,
    }
