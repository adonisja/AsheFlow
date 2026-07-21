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
from app.models.crew_compliance import CrewCompliance
from app.models.driver_check_in import DriverCheckIn
from app.models.rts_clearance import RTSReport, StationHandoff

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
            # Delete from DB first so the employee loses access atomically.
            # Cognito cleanup is best-effort afterwards; orphaned Cognito users
            # are harmless (disabled by AdminDisableUser if needed) but we
            # attempt deletion to keep the pool clean.
            db.delete(employee)
            deleted_db += 1

        db.commit()

        # Attempt Cognito cleanup after the DB transaction is committed.
        # Prefer username (the Cognito account identifier post-registration);
        # fall back to email for pre-registration accounts that only have
        # a Cognito user created via AdminCreateUser with email as the username.
        for employee in expired:
            cognito_username = employee.username or employee.email
            if not cognito_username:
                continue
            try:
                cognito.admin_delete_user(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                )
                deleted_cognito += 1
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "UserNotFoundException":
                    deleted_cognito += 1
                else:
                    logger.error(
                        "Failed to delete Cognito user %s: %s", cognito_username, e
                    )
                    cognito_failures.append(cognito_username)
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


@celery_app.task(name="app.tasks.cleanup.purge_expired_operational_records")
def purge_expired_operational_records() -> dict:
    """Delete operational shift records older than operational_record_retention_days.

    Covers: CrewCompliance, DriverCheckIn, RTSReport, StationHandoff.
    FLSA §211 requires employment records be kept for at least 3 years — the
    default retention period is 1095 days. Set operational_record_retention_days=0
    in config to disable this task.

    Returns a summary dict with per-table delete counts.
    """
    retention_days = settings.operational_record_retention_days
    if retention_days <= 0:
        logger.info("purge_expired_operational_records: disabled (retention_days=0).")
        return {"skipped": True}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    db = SessionLocal()
    counts: dict[str, int] = {}

    try:
        for model, label in (
            (CrewCompliance,  "crew_compliance"),
            (DriverCheckIn,   "driver_check_ins"),
            (RTSReport,       "rts_reports"),
            (StationHandoff,  "station_handoffs"),
        ):
            n = (
                db.query(model)
                .filter(model.submitted_at < cutoff)
                .delete(synchronize_session=False)
            )
            counts[label] = n

        db.commit()
        logger.info("purge_expired_operational_records: %s", counts)

    except Exception as e:
        db.rollback()
        logger.error("purge_expired_operational_records failed: %s", e)
        raise
    finally:
        db.close()

    return counts


@celery_app.task(name="app.tasks.cleanup.null_expired_delivery_addresses")
def null_expired_delivery_addresses() -> dict:
    """Null the customer delivery address on delivery rows older than
    delivery_address_retention_hours (ADR-219).

    Keeps block_key + counts + TBA — only the personal identifier is erased.
    Covers delivery_stops, routes (normalised_addresses ARRAY + the stops JSONB),
    misrouted_package_flags, rts_packages, missing_packages, reattempt_assignments.
    Prerequisite ADR-218 removed the last post-shift reader of the RTS address.
    Global maintenance (all companies). 0 disables.
    """
    hours = settings.delivery_address_retention_hours
    if hours <= 0:
        logger.info("null_expired_delivery_addresses: disabled (retention_hours=0).")
        return {"skipped": True}

    from app.models.walker_route import Route, MisroutedPackageFlag
    from app.models.delivery_stop import DeliveryStop
    from app.models.rts import RTSPackage, MissingPackage, DamagedPackage

    now = datetime.now(timezone.utc)
    cutoff_dt = now - timedelta(hours=hours)
    cutoff_date = cutoff_dt.date()
    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        # Routes older than the window: null the ARRAY + scrub the stops JSONB.
        old_routes = (
            db.query(Route)
            .filter(Route.route_date < cutoff_date, Route.normalised_addresses != [])
            .all()
        )
        n_routes = 0
        for r in old_routes:
            r.normalised_addresses = []
            if r.stops:
                # keep block_key + tba_numbers per stop; drop the address (ADR-194 double-storage)
                r.stops = [{k: v for k, v in (s or {}).items() if k != "address"} for s in r.stops]
            n_routes += 1
        counts["routes"] = n_routes

        # DeliveryStop: no own date → join Route.route_date.
        old_route_ids = [r.id for r in db.query(Route.id).filter(Route.route_date < cutoff_date).all()]
        counts["delivery_stops"] = (
            db.query(DeliveryStop)
            .filter(DeliveryStop.route_id.in_(old_route_ids),
                    DeliveryStop.normalised_address.isnot(None))
            .update({DeliveryStop.normalised_address: None}, synchronize_session=False)
            if old_route_ids else 0
        )

        # MisroutedPackageFlag has no own timestamp — key on the parent Route's date.
        counts["misroute_flags"] = (
            db.query(MisroutedPackageFlag)
            .filter(MisroutedPackageFlag.route_id.in_(old_route_ids),
                    MisroutedPackageFlag.normalised_address.isnot(None))
            .update({MisroutedPackageFlag.normalised_address: None}, synchronize_session=False)
            if old_route_ids else 0
        )
        counts["rts_packages"] = (
            db.query(RTSPackage)
            .filter(RTSPackage.recorded_at < cutoff_dt,
                    RTSPackage.normalised_address.isnot(None))
            .update({RTSPackage.normalised_address: None}, synchronize_session=False)
        )
        counts["missing_packages"] = (
            db.query(MissingPackage)
            .filter(MissingPackage.reported_at < cutoff_dt,
                    MissingPackage.normalised_address.isnot(None))
            .update({MissingPackage.normalised_address: None}, synchronize_session=False)
        )
        counts["damaged_packages"] = (
            db.query(DamagedPackage)
            .filter(DamagedPackage.route_date < cutoff_date,
                    DamagedPackage.normalised_address.isnot(None))
            .update({DamagedPackage.normalised_address: None}, synchronize_session=False)
        )

        db.commit()
        logger.info("null_expired_delivery_addresses: %s", counts)
        return counts
    except Exception as e:
        db.rollback()
        logger.error("null_expired_delivery_addresses failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.decay_troublesome_scores")
def decay_troublesome_scores() -> dict:
    """Nightly decay of BuildingProfile.troublesome_score (ADR-218).

    ~30-day half-life; scores below the floor snap to 0. Global (all companies),
    like the other cleanup tasks. Lets the troublesome signal fade as buildings
    improve, with no delivery-row retention needed to recompute it.
    """
    from app.services.building_troublesome import decay_all
    db = SessionLocal()
    try:
        n = decay_all(db)
        db.commit()
        logger.info("decay_troublesome_scores: decayed %d building(s).", n)
        return {"decayed": n}
    except Exception as e:
        db.rollback()
        logger.error("decay_troublesome_scores failed: %s", e)
        raise
    finally:
        db.close()
