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
    include=["app.tasks.cleanup", "app.tasks.training_deadlines", "app.tasks.dispatch_alerts", "app.tasks.eod_reminders", "app.tasks.adp_sync", "app.tasks.adp_timecard_sync", "app.tasks.adp_mismatch_detect", "app.tasks.adp_urgency_escalation", "app.tasks.failed_adp_writes"]
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
