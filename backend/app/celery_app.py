"""Celery application and Beat schedule for AsheFlow.

Beat runs inside the celery_worker container and fires scheduled tasks.
Redis (already used for dispatch state) doubles as the message broker and
result backend — no additional infrastructure required.

Usage (inside the celery_worker container):
    celery -A app.celery_app worker --beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "asheflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.cleanup", "app.tasks.training_deadlines", "app.tasks.dispatch_alerts", "app.tasks.eod_reminders", "app.tasks.adp_sync", "app.tasks.adp_timecard_sync", "app.tasks.adp_pay_period_sync", "app.tasks.adp_mismatch_detect", "app.tasks.adp_urgency_escalation", "app.tasks.failed_adp_writes", "app.tasks.enrich_manifest", "app.tasks.run_sort_task", "app.tasks.sort_rollup", "app.tasks.resolve_building_addresses", "app.tasks.enrich_geometry", "app.tasks.role_directory", "app.tasks.integration_health"]
)

celery_app.conf.update(
    # Use JSON so task payloads are human-readable in Redis
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/New_York",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    # Every 10 min — sweeps BuildingProfiles left `pending` by a submit whose
    # .delay() dispatch was lost (broker restart, worker down). The submit path
    # queues resolution immediately (ADR-277 D1); this is the safety net, not
    # the mechanism, so the interval only bounds how long a dropped dispatch
    # stays invisible. A `pending` profile is excluded from routing lookups, so
    # the cost of the gap is a building the crew cannot see yet — not bad data.
    # ADR-315 — fill PlaceType's geometry tier from GeoClient. Nightly because
    # enrichment has no deadline: nothing downstream fails without it, and a
    # zone bootstrapped today is fully enriched by tomorrow. Bounded batch, so
    # a large zone is finished by the next run rather than one long job.
    # ADR-317 D1 — surface a role whose Cognito group is missing or empty before
    # a captain finds out by losing every tab. Reports, never enforces.
    "check-role-directory-drift": {
        "task": "app.tasks.role_directory.check_role_directory_drift",
        "schedule": crontab(hour=5, minute=0),
    },
    "enrich-place-geometry": {
        "task": "app.tasks.enrich_geometry.enrich_place_geometry",
        "schedule": crontab(hour=4, minute=30),
    },
    "resolve-building-addresses": {
        "task": "app.tasks.resolve_building_addresses.resolve_pending_addresses",
        "schedule": crontab(minute="*/10"),
    },
    # ADR-337 — every 10 min. Every integration alert before this fired only
    # when someone USED the integration, which is how a revoked Discord token
    # crash-looped the bot for weeks and surfaced when a dispatcher reported
    # that messages had stopped.
    #
    # Ten minutes is chosen against the cost of being wrong either way: a
    # credential revoked at 09:00 is known by 09:10 rather than whenever someone
    # next publishes, and three read-only calls per run is negligible. Tighter
    # buys nothing — nobody rotates a token expecting sub-minute detection —
    # and looser approaches "a dispatcher would have noticed first", which is
    # the failure being fixed.
    #
    # It also CLEARS on success, which is what makes SES and Cognito alerts
    # self-closing (ADR-336's Open item): they have no natural heartbeat of
    # their own, so without this they sat on the board until tidied by hand.
    "check-integration-health": {
        "task": "app.tasks.integration_health.check_integration_health",
        "schedule": crontab(minute="*/10"),
    },
    # 03:00 AM Eastern — quiet period, low API traffic
    "expire-pending-invites-daily": {
        "task": "app.tasks.cleanup.expire_pending_invites",
        "schedule": crontab(hour=3, minute=0),
    },
    # 00:01 AM Eastern — flag training records not submitted before midnight
    "check-training-submissions-nightly": {
        "task": "app.tasks.training_deadlines.check_training_submissions",
        "schedule": crontab(hour=0, minute=1),
    },
    # 09:05 AM Eastern — remind dispatch that 09:10 finalization deadline is approaching
    "dispatch-finalization-reminder": {
        "task": "app.tasks.dispatch_alerts.alert_finalization_deadline",
        "schedule": crontab(hour=9, minute=5),
    },
    # 17:00 Eastern — first fuel/mileage log reminder for drivers who haven't submitted
    "fuel-log-reminder-first": {
        "task": "app.tasks.eod_reminders.remind_fuel_log_missing",
        "schedule": crontab(hour=17, minute=0),
    },
    # 18:30 Eastern — second pass for drivers still missing their fuel log (late returns)
    "fuel-log-reminder-second": {
        "task": "app.tasks.eod_reminders.remind_fuel_log_missing",
        "schedule": crontab(hour=18, minute=30),
    },
    # 01:00 AM Eastern Sunday — refresh the ADP pay period schedule. Runs ahead of
    # the employee/timecard syncs because mismatch detection resolves a pay period
    # per timecard and skips the timecard when none covers its work_date (ADR-233).
    "sync-adp-pay-periods-weekly": {
        "task": "app.tasks.adp_pay_period_sync.sync_adp_pay_periods",
        "schedule": crontab(hour=1, minute=0, day_of_week=0),
    },
    # 02:00 AM Eastern — sync ADP employee roster for all enabled integrations
    "sync-adp-employees-nightly": {
        "task": "app.tasks.adp_sync.sync_adp_employees",
        "schedule": crontab(hour=2, minute=0),
    },
    # 03:30 AM Eastern on the 1st of every month — purge operational records
    # older than operational_record_retention_days (default 1095 / 3 years, FLSA §211).
    "purge-expired-operational-records-monthly": {
        "task": "app.tasks.cleanup.purge_expired_operational_records",
        "schedule": crontab(hour=3, minute=30, day_of_month=1),
    },
    # 02:30 AM Eastern — decay BuildingProfile troublesome scores (~30d half-life, ADR-218).
    "decay-troublesome-scores-nightly": {
        "task": "app.tasks.cleanup.decay_troublesome_scores",
        "schedule": crontab(hour=2, minute=30),
    },
    # 03:15 AM Eastern — delete notifications older than notification_retention_days
    # (default 3, read or unread) + any expired (ADR-227). Bounds the table + SSE poll.
    "prune-notifications-nightly": {
        "task": "app.tasks.cleanup.prune_notifications",
        "schedule": crontab(hour=3, minute=15),
    },
    # 03:45 AM Eastern — roll yesterday's sort decisions into route_sort_daily
    # (ADR-273). Each company rolls up ITS OWN yesterday, so completed-day-only
    # holds across timezones. Runs BEFORE the 04:00 address nulling: the rollup
    # reads DeliveryStop counts (never addresses), so the order is not a
    # dependency — but keeping it earlier means a same-night manual backfill
    # sees the day intact.
    "roll-up-sort-metrics-nightly": {
        "task": "app.tasks.sort_rollup.roll_up_sort_metrics",
        "schedule": crontab(hour=3, minute=45),
    },
    # 04:00 AM Eastern — null delivery-row customer addresses older than
    # delivery_address_retention_hours (default 48h, ADR-219). Keeps block_key + counts.
    # ADR-281: ORE certificates carry trainee PII and expire at 48h. Runs just
    # after the address nulling, which is the same retention discipline.
    "purge-expired-ore-certificates-nightly": {
        "task": "app.tasks.cleanup.purge_expired_ore_certificates",
        "schedule": crontab(hour=4, minute=15),
    },
    "null-expired-delivery-addresses-nightly": {
        "task": "app.tasks.cleanup.null_expired_delivery_addresses",
        "schedule": crontab(hour=4, minute=0),
    },
    # 04:30 AM Eastern — redact departed employees' denormalized name copies
    # past employee_name_retention_days (default 180, ADR-221).
    "redact-departed-employee-names-nightly": {
        "task": "app.tasks.cleanup.redact_departed_employee_names",
        "schedule": crontab(hour=4, minute=30),
    },
    # 06:00 AM Eastern — fetch previous day's ADP timecards for all verified employees
    "fetch-adp-timecards-daily": {
        "task": "app.tasks.adp_timecard_sync.sync_adp_timecards",
        "schedule": crontab(hour=6, minute=0),
    },
    # 12:00 PM Eastern - Run ADP mismatch detections for each company
    "run-adp-vs-flex-mismatch-detection-daily": {
        "task": "app.tasks.adp_mismatch_detect.detect_timecard_mismatches",
        "schedule": crontab(hour=12, minute=0)
    },
    # 12:00 AM Eastern Saturday and Sunday - Escalate ADP status if necessary
    "escalate-adp-mismatch-statuses": {
        "task": "app.tasks.adp_urgency_escalation.escalate_adjustment_urgency",
        "schedule": crontab(hour=0, minute=5, day_of_week="6,0")
    },
    "retry-failed-adp-writes-weekend": {
        "task": "app.tasks.failed_adp_writes.retry_failed_adp_writes",
        "schedule": crontab(minute=0, hour="0,2,4,6,8,10,12,14,16,18,20,22", day_of_week="6,0"),
    },
    "retry-failed-adp-writes-final": {
        "task": "app.tasks.failed_adp_writes.retry_failed_adp_writes",
        "schedule": crontab(hour=18, minute=0, day_of_week=1),
    },
}
