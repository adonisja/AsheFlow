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
    """Delete UNREGISTERED invites (and their Cognito users) that have gone stale.

    Safe to run multiple times — only targets rows where:
    - account_status = 'pending_verification'
    - invited_at < now - INVITE_EXPIRY_DAYS
    - username IS NULL  (never completed registration)

    ADR-379 D1 — that last term is the whole point, and it was missing.

    `account_status` carries TWO meanings and this job only knew one.
    `complete_registration` deliberately leaves the status alone (its own comment:
    "account_status stays pending_verification until they actually sign in"), and
    only `get_caller_employee` promotes it, on an authenticated API call rather
    than on Cognito sign-in.

    So an employee invited on day 1 who registered on day 6 and first signs in on
    day 8 was DELETED on day 7 -- DB row and Cognito user both -- having done
    everything asked of them.

    `username` is the registration marker because it is set only by
    complete_registration, and `resend-credentials` already keys off it to tell
    "registered, not signed in" from "never registered" (registration.py:214).
    One definition of registered, not two.

    NOT `cognito_sub`: complete_registration tolerates it being None when the
    attribute is absent from the AdminCreateUser response, so it can be null on a
    genuinely registered employee. `username` cannot.

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
                # ADR-379 D1 — never registered. Without this the job deletes
                # employees who completed registration and simply have not
                # signed in yet.
                Employee.username.is_(None),
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


@celery_app.task(name="app.tasks.cleanup.expire_registered_unused")
def expire_registered_unused() -> dict:
    """Delete accounts that completed registration but never signed in (ADR-379 D2).

    A DIFFERENT question from a stale invite, which is why it is a different
    task on a different clock. `expire_pending_invites` asks "did this invite go
    unanswered"; this asks "was this account ever used". Folding them together is
    what produced the bug D1 fixed -- one filter serving two meanings.

    Never expiring these is not an option either: a registered account is a live
    Cognito user whose temporary password was emailed to someone. Leaving it
    forever leaves that credential live forever.

    Selects the exact complement of D1's filter: `username IS NOT NULL`.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.registered_unused_expiry_days
    )
    db = SessionLocal()
    deleted_db = 0
    deleted_cognito = 0
    cognito_failures: list = []

    try:
        stale = (
            db.query(Employee)
            .filter(
                # Still never signed in -- get_caller_employee promotes to
                # `active` on the first authenticated call.
                #
                # ADR-468 D2. This read `== "pending_verification"` AND
                # `username IS NOT NULL`, which was the definition of "registered"
                # BEFORE the column could say it. ADR-468 D1 moves exactly that
                # population to 'registered', so the two terms became mutually
                # exclusive and this sweep would have matched nothing -- silently,
                # forever, leaving every unused credential alive. A dead sweep
                # reports "nothing to expire" and looks healthy.
                #
                # Both states accepted: 'registered' is the post-migration truth,
                # and 'pending_verification' stays so a row created by some path
                # that stamps a username without the status is still swept.
                Employee.account_status.in_(("pending_verification", "registered")),
                Employee.invited_at < cutoff,
                # Registered. The complement of expire_pending_invites, so the
                # two tasks partition the space rather than overlapping.
                Employee.username.isnot(None),
            )
            .all()
        )

        if not stale:
            logger.info("expire_registered_unused: nothing to expire.")
            return {"deleted_db": 0, "deleted_cognito": 0, "cognito_failures": []}

        cognito = boto3.client("cognito-idp", region_name=settings.aws_region)

        # Same order as expire_pending_invites: DB first so access is lost
        # atomically, Cognito best-effort afterwards.
        for employee in stale:
            db.delete(employee)
            deleted_db += 1
        db.commit()

        for employee in stale:
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
                if e.response["Error"]["Code"] == "UserNotFoundException":
                    deleted_cognito += 1
                else:
                    # No email or username in the message beyond the Cognito
                    # identifier already required to name the failure (D7).
                    logger.error(
                        "Failed to delete Cognito user %s: %s", cognito_username, e
                    )
                    cognito_failures.append(cognito_username)

        logger.info(
            "expire_registered_unused: deleted %d DB records, %d Cognito users. Failures: %s",
            deleted_db, deleted_cognito, cognito_failures,
        )
    except Exception as e:
        db.rollback()
        logger.error("expire_registered_unused task failed: %s", e)
        raise
    finally:
        db.close()

    return {
        "deleted_db": deleted_db,
        "deleted_cognito": deleted_cognito,
        "cognito_failures": cognito_failures,
    }


@celery_app.task(name="app.tasks.cleanup.purge_expired_acknowledgements")
def purge_expired_acknowledgements() -> dict:
    """Delete notification acknowledgements older than acknowledgement_retention_days.

    ADR-494. FLSA §211 requires employment records be kept at least 3 years, and
    a `timecard_mismatch` acknowledgement IS a wage-and-hour record — the
    employee attests to their own hours and breaks. That is the
    longest-justified of the five interruptive types, so it sets the window for
    all of them: one clock and one cited statute, rather than a per-type map
    that drifts from the registry every time a type is added.

    COUNTED FROM `acknowledged_at`, NOT THE NOTIFICATION.
    `prune_notifications` deletes the notification after 3 days and the FK is
    SET NULL, so by the time this fires `notification_id` has been NULL for
    roughly three years. Joining to `notifications` here would match nothing and
    silently delete nothing — the shape of bug that reports success forever.

    This is the LAST thing holding the row, so a bug here is unrecoverable:
    there is no soft-delete and no archive. Hence the explicit cutoff log and
    the count in the return value.

    Set acknowledgement_retention_days=0 to disable.
    """
    from app.models.role_guide import NotificationAcknowledgement

    retention_days = settings.acknowledgement_retention_days
    if retention_days <= 0:
        logger.info("purge_expired_acknowledgements: disabled (retention_days=0).")
        return {"skipped": True}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    db = SessionLocal()
    try:
        deleted = (
            db.query(NotificationAcknowledgement)
            .filter(NotificationAcknowledgement.acknowledged_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(
            "purge_expired_acknowledgements: deleted %d (cutoff %s, %d days).",
            deleted, cutoff.date(), retention_days,
        )
        return {
            "deleted": deleted,
            "cutoff": cutoff.date().isoformat(),
            "days": retention_days,
        }
    except Exception as e:
        db.rollback()
        # type(e).__name__ only: a retention job's failure goes to an operator,
        # and str(e) on a DB error can carry row contents.
        logger.error("purge_expired_acknowledgements failed: %s", type(e).__name__)
        raise
    finally:
        db.close()


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
    from app.models.tote_address import ToteAddress

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

        # ADR-291: captain-entered tote addresses are customer delivery addresses
        # and inherit this purge like any other. Being typed by a captain rather
        # than supplied by Amazon changes nothing about what they are.
        #
        # BOTH columns: raw_address is what the captain typed and is just as
        # identifying as the normalised form. block_key survives deliberately —
        # it is what the sort routes on and cannot reconstruct a house number.
        counts["tote_addresses"] = (
            db.query(ToteAddress)
            .filter(
                ToteAddress.entry_date < cutoff_date,
                (ToteAddress.raw_address.isnot(None))
                | (ToteAddress.normalised_address.isnot(None))
                | (ToteAddress.lat.isnot(None))
                | (ToteAddress.first_cross_street.isnot(None)),
            )
            .update(
                # ADR-587 D5: the door's coordinates and cross streets go with
                # its address. The block key and the street segment stay (ADR-279 D4).
                {ToteAddress.raw_address: None, ToteAddress.normalised_address: None,
                 ToteAddress.lat: None, ToteAddress.lng: None,
                 ToteAddress.first_cross_street: None, ToteAddress.second_cross_street: None},
                synchronize_session=False,
            )
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


@celery_app.task(name="app.tasks.cleanup.redact_departed_employee_names")
def redact_departed_employee_names() -> dict:
    """Redact denormalized name copies for employees deactivated > retention window
    ago (ADR-221). Runs on the still-linked tombstone (FK intact) so the paired-FK
    match works; scrubs the employee row's own PII too. 0 disables.
    """
    days = settings.employee_name_retention_days
    if days <= 0:
        logger.info("redact_departed_employee_names: disabled (retention_days=0).")
        return {"skipped": True}

    from app.services.employee_redaction import redact_employee_names, REDACTED_NAME
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        departed = (
            db.query(Employee)
            .filter(
                Employee.deactivated_at.isnot(None),
                Employee.deactivated_at < cutoff,
                Employee.legal_name != REDACTED_NAME,   # not already redacted (ADR-567: the record name)
            )
            .all()
        )
        total = 0
        for emp in departed:
            redact_employee_names(db, emp.id)
            total += 1
        db.commit()
        logger.info("redact_departed_employee_names: redacted %d departed employee(s).", total)
        return {"redacted_employees": total}
    except Exception as e:
        db.rollback()
        logger.error("redact_departed_employee_names failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.decay_troublesome_scores")
def decay_troublesome_scores() -> dict:
    """Nightly decay of troublesome door scores (ADR-218; on troublesome_doors since ADR-584 D6).

    ~30-day half-life; scores below the floor snap to 0. Global (all companies),
    like the other cleanup tasks. Lets the troublesome signal fade as buildings
    improve, with no delivery-row retention needed to recompute it.
    """
    from app.services.building_troublesome import decay_all
    db = SessionLocal()
    try:
        n = decay_all(db)
        db.commit()
        logger.info("decay_troublesome_scores: decayed %d door(s).", n)
        return {"decayed": n}
    except Exception as e:
        db.rollback()
        logger.error("decay_troublesome_scores failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.prune_notifications")
def prune_notifications() -> dict:
    """Delete stale notifications (ADR-227). Global (all companies). 0 disables.

    Removes anything older than notification_retention_days (read OR unread — an
    operational notice's shift is long over after a few days), PLUS any expired
    notification (past expires_at) regardless of age. The inbox already hides
    expired/old ones; this reclaims the storage so the table (and the 10s SSE
    poll that scans it) doesn't grow unbounded. Automates the manual
    DELETE /notifications/prune endpoint.
    """
    from sqlalchemy import or_
    from app.models.notification import Notification

    days = settings.notification_retention_days
    if days <= 0:
        logger.info("prune_notifications: disabled (retention_days=0).")
        return {"skipped": True}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = (
            db.query(Notification)
            .filter(
                or_(
                    Notification.created_at < cutoff,                              # aged out (read or unread)
                    (Notification.expires_at.isnot(None)) & (Notification.expires_at <= now),  # expired
                )
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info("prune_notifications: deleted %d notification(s) (cutoff %s).", deleted, cutoff.date())
        return {"deleted": deleted, "cutoff": cutoff.date().isoformat(), "days": days}
    except Exception as e:
        db.rollback()
        logger.error("prune_notifications failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.purge_expired_ore_certificates")
def purge_expired_ore_certificates() -> dict:
    """Delete ORE certificates past their retention window (ADR-281 D3).

    An S3 lifecycle rule expires these at 1 day as a backstop, but lifecycle is
    eventually consistent and 48h here is a privacy commitment, not an
    optimisation — so the sweep deletes precisely and nulls the key.

    The ATTESTATION survives: ore_completed_at and ore_certificate_uploaded_by
    are untouched. A NULL key with a non-null ore_completed_at is what the API
    reads as "certificate expired", which is a different answer to a manager
    than "never uploaded".

    Idempotent — safe to re-run, and safe when S3 already removed the object.
    """
    from app.models.training import TrainingRecord
    from app.services import ore_certificates

    if not ore_certificates.is_enabled():
        logger.info("purge_expired_ore_certificates: storage not configured, skipping.")
        return {"deleted": 0, "failed": 0, "skipped": True}

    db = SessionLocal()
    deleted = failed = 0
    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(TrainingRecord)
            .filter(
                TrainingRecord.ore_certificate_key.isnot(None),
                TrainingRecord.ore_certificate_expires_at < now,
            )
            .all()
        )
        for record in expired:
            if ore_certificates.delete(record.ore_certificate_key):
                # Null the key ONLY on a confirmed delete. Nulling after a
                # failure would orphan the object: nothing would point at it,
                # so nothing would ever try again, and it would sit past its
                # retention window until the lifecycle rule happened to catch it.
                record.ore_certificate_key = None
                record.ore_certificate_expires_at = None
                deleted += 1
            else:
                failed += 1
        db.commit()
        logger.info(
            "purge_expired_ore_certificates: done",
            extra={"deleted": deleted, "failed": failed},
        )
        return {"deleted": deleted, "failed": failed, "skipped": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.expire_owner_email_changes")
def expire_owner_email_changes() -> dict:
    """Drop Owner email changes nobody confirmed (ADR-451 D5).

    THE REVERT IS THAT NOTHING WAS EVER WRITTEN. `email` was never touched, so
    clearing `pending_email` returns the record to exactly its prior state --
    there is no old value to restore and no window where the Owner's sign-in
    address was wrong.

    Why this sweep exists at all, given the token also expires: a stale
    `pending_email` is still DISPLAYED. Someone reading the record months later
    would see an address the Owner does not use and cannot sign in with, beside
    one they do -- and have no way to tell which is real.

    Idempotent: a row with no pending change does not match.
    """
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    cleared = 0
    try:
        stale = (
            db.query(Employee)
            .filter(
                Employee.pending_email.isnot(None),
                Employee.pending_email_expires_at < now,
            )
            .all()
        )
        for emp in stale:
            # The employee id, never the address (Dimension 7): a log is a
            # wider audience than the record it describes.
            logger.info(
                "Expiring unconfirmed Owner email change for employee %s (company %s).",
                emp.id, emp.company_id,
            )
            emp.pending_email = None
            emp.pending_email_expires_at = None
            cleared += 1

        if cleared:
            db.commit()
        return {"cleared": cleared}
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.expire_trainee_credentials")
def expire_trainee_credentials() -> dict:
    """Destroy trainee Flex credentials nobody confirmed (ADR-491 D2).

    Management issues temporary credentials and the trainee changes both on first
    sign-in. A row still holding values `trainee_credential_retention_days` after
    it was sent is a live Amazon login nobody needs AsheFlow to keep: the values
    are nulled and `expired_at` stamped. The row stays as a status record, so
    management sees "Expired" rather than nothing. Global. 0 disables.
    """
    from app.models.trainee_credentials import TraineeCredentials

    days = settings.trainee_credential_retention_days
    if days <= 0:
        logger.info("expire_trainee_credentials: disabled (retention_days=0).")
        return {"skipped": True}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    db = SessionLocal()
    try:
        expired = (
            db.query(TraineeCredentials)
            .filter(
                TraineeCredentials.flex_email.isnot(None),
                TraineeCredentials.sent_at < cutoff,
            )
            .update(
                {
                    TraineeCredentials.flex_email: None,
                    TraineeCredentials.clock_in_code: None,
                    TraineeCredentials.expired_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        logger.info("expire_trainee_credentials: expired %d row(s) (cutoff %s).", expired, cutoff.date())
        return {"expired": expired, "cutoff": cutoff.date().isoformat(), "days": days}
    except Exception as e:
        db.rollback()
        logger.error("expire_trainee_credentials failed: %s", type(e).__name__)
        raise
    finally:
        db.close()


def _iso_week_monday(week: str):
    """"2026-W28" → the Monday it began, or None if the label does not parse."""
    import re
    from datetime import date
    m = re.match(r"^\s*(\d{4})-W(\d{1,2})\s*$", week or "")
    if not m:
        return None
    try:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


@celery_app.task(name="app.tasks.cleanup.purge_expired_scorecards")
def purge_expired_scorecards() -> dict:
    """Retention for individual Amazon scorecards and unmatched imports (ADR-492).

    D1 — delete `scope='individual'` scorecards whose ISO week began more than
    `scorecard_retention_days` ago, EXCEPT those under a retention hold (D3) or
    referenced by an open appeal (draft/submitted — deleting would erase the
    dispute mid-flight). Company scorecards carry no person and are exempt.

    Children are deleted explicitly, deepest first (ADR-231): an unverified
    ON DELETE CASCADE is a delete you did not write.

    D4 — delete every `scorecard_import_pending` row for a (company,
    transporter_id) whose NEWEST row is older than
    `scorecard_pending_retention_days`, so an ID still arriving weekly keeps
    its history.

    Global (all companies). Each half is disabled by its own setting being 0.
    """
    from datetime import date
    from sqlalchemy import func, or_
    from app.models.scorecard import Scorecard, ScorecardMetric
    from app.models.scorecard_appeal import ScorecardAppeal, ScorecardAppealItem
    from app.models.scorecard_import import ScorecardImportPending

    out: dict = {}
    today = date.today()
    db = SessionLocal()
    try:
        days = settings.scorecard_retention_days
        if days > 0:
            cutoff = today - timedelta(days=days)
            open_appeal = (
                db.query(ScorecardAppeal.scorecard_id)
                .filter(ScorecardAppeal.status.in_(("draft", "submitted")))
            )
            candidates = (
                db.query(Scorecard.id, Scorecard.week)
                .filter(
                    Scorecard.scope == "individual",
                    Scorecard.retention_hold_indefinite.is_(False),
                    or_(Scorecard.retention_hold_until.is_(None),
                        Scorecard.retention_hold_until < today),
                    Scorecard.id.notin_(open_appeal),
                )
                .all()
            )
            unparseable = 0
            ids = []
            for sid, week in candidates:
                monday = _iso_week_monday(week)
                if monday is None:
                    unparseable += 1     # kept: never delete what we cannot date
                elif monday < cutoff:
                    ids.append(sid)

            if ids:
                appeal_ids = db.query(ScorecardAppeal.id).filter(ScorecardAppeal.scorecard_id.in_(ids))
                out["appeal_items"] = (
                    db.query(ScorecardAppealItem)
                    .filter(ScorecardAppealItem.appeal_id.in_(appeal_ids))
                    .delete(synchronize_session=False)
                )
                out["appeals"] = (
                    db.query(ScorecardAppeal).filter(ScorecardAppeal.scorecard_id.in_(ids))
                    .delete(synchronize_session=False)
                )
                out["metrics"] = (
                    db.query(ScorecardMetric).filter(ScorecardMetric.scorecard_id.in_(ids))
                    .delete(synchronize_session=False)
                )
                out["scorecards"] = (
                    db.query(Scorecard).filter(Scorecard.id.in_(ids))
                    .delete(synchronize_session=False)
                )
            else:
                out["scorecards"] = 0
            out["unparseable_weeks_kept"] = unparseable
            out["cutoff"] = cutoff.isoformat()

        pdays = settings.scorecard_pending_retention_days
        if pdays > 0:
            pcutoff = datetime.now(timezone.utc) - timedelta(days=pdays)
            stale = (
                db.query(ScorecardImportPending.company_id, ScorecardImportPending.transporter_id)
                .group_by(ScorecardImportPending.company_id, ScorecardImportPending.transporter_id)
                .having(func.max(ScorecardImportPending.created_at) < pcutoff)
                .all()
            )
            n = 0
            for company_id, tid in stale:
                n += (
                    db.query(ScorecardImportPending)
                    .filter(ScorecardImportPending.company_id == company_id,
                            ScorecardImportPending.transporter_id == tid)
                    .delete(synchronize_session=False)
                )
            out["pending_rows"] = n
            out["pending_ids"] = len(stale)

        db.commit()
        logger.info("purge_expired_scorecards: %s", out)
        return out
    except Exception as e:
        db.rollback()
        logger.error("purge_expired_scorecards failed: %s", type(e).__name__)
        raise
    finally:
        db.close()


# ADR-493 D4/D8. The nightly passes look back this far behind their cutoff, so
# the work per run is bounded by recent history instead of growing forever.
# A missed run is caught up as long as the gap is shorter than this; history
# older than the window is handled ONCE by `backfill=True` at deploy.
PI_RETENTION_WINDOW_DAYS = 30


def _expire_tbas(db, cutoff_date, window_start) -> dict:
    """Replace TBAs on delivery rows dated in [window_start, cutoff_date) with
    per-value placeholders. Lengths kept: package counts are len(tba_numbers)."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.walker_route import Route, MisroutedPackageFlag
    from app.models.delivery_stop import DeliveryStop
    from app.models.rts import RTSPackage, MissingPackage, DamagedPackage
    from app.models.tote_ops import PackageRemoval
    from app.models.truck_zone import TruckZone
    from app.services.pi_erasure import placeholder, placeholder_all, is_placeholder, scrub_roster

    counts: dict[str, int] = {}

    def in_window(col):
        q = [col < cutoff_date]
        if window_start is not None:
            q.append(col >= window_start)
        return q

    def bump(label, n):
        if n:
            counts[label] = counts.get(label, 0) + n

    routes = db.query(Route).filter(*in_window(Route.route_date)).all()
    route_ids = [r.id for r in routes]
    for r in routes:
        new, n = placeholder_all(r.tba_numbers)
        if n:
            r.tba_numbers = new
            flag_modified(r, "tba_numbers")
            bump("routes.tba_numbers", n)
        if r.stops:
            changed, total = [], 0
            for st in r.stops:
                st = dict(st or {})
                if isinstance(st.get("tba_numbers"), list):
                    st["tba_numbers"], k = placeholder_all(st["tba_numbers"])
                    total += k
                changed.append(st)
            if total:
                r.stops = changed
                flag_modified(r, "stops")
                bump("routes.stops", total)

    if route_ids:
        for stop in db.query(DeliveryStop).filter(DeliveryStop.route_id.in_(route_ids)).all():
            new, n = placeholder_all(stop.tba_numbers)
            if n:
                stop.tba_numbers = new
                flag_modified(stop, "tba_numbers")
                bump("delivery_stops.tba_numbers", n)
        for f in db.query(MisroutedPackageFlag).filter(MisroutedPackageFlag.route_id.in_(route_ids)).all():
            if f.tba_number and not is_placeholder(f.tba_number):
                f.tba_number = placeholder()
                bump("misrouted_package_flags.tba_number", 1)

    cutoff_dt = datetime.combine(cutoff_date, datetime.min.time(), tzinfo=timezone.utc)
    start_dt = (datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc)
                if window_start is not None else None)
    for model, col, label in (
        (RTSPackage, RTSPackage.recorded_at, "rts_packages.tba_number"),
        (MissingPackage, MissingPackage.reported_at, "missing_packages.tba_number"),
    ):
        q = db.query(model).filter(col < cutoff_dt)
        if start_dt is not None:
            q = q.filter(col >= start_dt)
        for row in q.all():
            if row.tba_number and not is_placeholder(row.tba_number):
                row.tba_number = placeholder()
                bump(label, 1)

    for row in db.query(DamagedPackage).filter(*in_window(DamagedPackage.route_date)).all():
        if row.tba_number and not is_placeholder(row.tba_number):
            row.tba_number = placeholder()
            bump("damaged_packages.tba_number", 1)

    for row in db.query(PackageRemoval).filter(*in_window(PackageRemoval.removal_date)).all():
        if row.tba and not is_placeholder(row.tba):
            row.tba = None
            bump("package_removals.tba", 1)
        new, n = placeholder_all(row.tba_numbers)
        if n:
            row.tba_numbers = new
            flag_modified(row, "tba_numbers")
            bump("package_removals.tba_numbers", n)

    for z in db.query(TruckZone).filter(*in_window(TruckZone.zone_date)).all():
        new, n = placeholder_all(z.package_tbas)
        if n:
            z.package_tbas = new
            flag_modified(z, "package_tbas")
            bump("truck_zones.package_tbas", n)
        # ADR-587 D4: the roster repeats every TBA, and a loose bag's id is one.
        new, n = scrub_roster(z.tote_roster)
        if n:
            z.tote_roster = new
            flag_modified(z, "tote_roster")
            bump("truck_zones.tote_roster", n)

    return counts


def _blank_audit_keys(db, keys, cutoff_dt, start_dt) -> int:
    """ADR-493 D8 — audit snapshots copied addresses and TBAs that the row-level
    retention then cleared, so the copies outlived the originals indefinitely."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.audit_log import AuditLog
    from app.services.pi_erasure import blank_keys, AUDIT_EXEMPT_TARGETS

    q = db.query(AuditLog).filter(
        AuditLog.created_at < cutoff_dt,
        AuditLog.target_table.notin_(AUDIT_EXEMPT_TARGETS),
    )
    if start_dt is not None:
        q = q.filter(AuditLog.created_at >= start_dt)
    total = 0
    for a in q.all():
        for col in ("before_snapshot", "after_snapshot"):
            snap = getattr(a, col)
            if snap:
                new, n = blank_keys(snap, keys)
                if n:
                    setattr(a, col, new)
                    flag_modified(a, col)
                    total += n
    return total


@celery_app.task(name="app.tasks.cleanup.expire_package_ids_and_audit_pi")
def expire_package_ids_and_audit_pi(backfill: bool = False) -> dict:
    """ADR-493 D4 + D8, nightly.

    1. TBAs on delivery rows older than `tba_retention_days` → placeholders.
    2. TBA values in audit snapshots on the same clock.
    3. Address values in audit snapshots older than
       `delivery_address_retention_hours` — the copies ADR-219's 48h nulling
       never reached.

    Each pass covers a PI_RETENTION_WINDOW_DAYS window behind its cutoff;
    `backfill=True` drops the lower bound (run once at deploy). Global.
    """
    from app.services.pi_erasure import AUDIT_ADDRESS_KEYS, AUDIT_TBA_KEYS

    now = datetime.now(timezone.utc)
    out: dict = {"backfill": backfill}
    db = SessionLocal()
    try:
        days = settings.tba_retention_days
        if days > 0:
            cutoff = now.date() - timedelta(days=days)
            start = None if backfill else cutoff - timedelta(days=PI_RETENTION_WINDOW_DAYS)
            out["tbas"] = _expire_tbas(db, cutoff, start)
            cutoff_dt = now - timedelta(days=days)
            start_dt = None if backfill else cutoff_dt - timedelta(days=PI_RETENTION_WINDOW_DAYS)
            out["audit_tba_values"] = _blank_audit_keys(db, AUDIT_TBA_KEYS, cutoff_dt, start_dt)

        hours = settings.delivery_address_retention_hours
        if hours > 0:
            cutoff_dt = now - timedelta(hours=hours)
            start_dt = None if backfill else cutoff_dt - timedelta(days=PI_RETENTION_WINDOW_DAYS)
            out["audit_address_values"] = _blank_audit_keys(db, AUDIT_ADDRESS_KEYS, cutoff_dt, start_dt)

        db.commit()
        logger.info("expire_package_ids_and_audit_pi: %s", out)
        return out
    except Exception as e:
        db.rollback()
        logger.error("expire_package_ids_and_audit_pi failed: %s", type(e).__name__)
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.cleanup.clear_stolen_package_pi")
def clear_stolen_package_pi() -> dict:
    """Clear a stolen-package report's customer address and TBAs at 60 days (ADR-512 D5).

    Counts, flags, LMET, the summary and the anchor point (the DSP's own staging
    point) stay: the report remains useful as a record of what happened, without
    the customer's door or the package ids. `pi_cleared_at` is stamped so "empty
    because cleared" is distinguishable from "never entered".

    Counted from `incident_date`, the event, not `created_at`: a report filed a
    week late must not keep the address a week longer.
    """
    from app.models.stolen_package_report import StolenPackageReport

    days = settings.stolen_package_pi_retention_days
    if days <= 0:
        logger.info("clear_stolen_package_pi: disabled (retention_days=0).")
        return {"skipped": True}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    db = SessionLocal()
    try:
        rows = (
            db.query(StolenPackageReport)
            .filter(
                StolenPackageReport.incident_date < cutoff,
                StolenPackageReport.pi_cleared_at.is_(None),
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for r in rows:
            r.incident_address = None
            r.tbas = []
            r.pi_cleared_at = now
        db.commit()
        if rows:
            logger.info("clear_stolen_package_pi: cleared %d report(s) before %s.", len(rows), cutoff)
        return {"cleared": len(rows), "cutoff": cutoff.isoformat(), "days": days}
    except Exception as e:
        db.rollback()
        logger.error("clear_stolen_package_pi failed: %s", type(e).__name__)
        raise
    finally:
        db.close()
