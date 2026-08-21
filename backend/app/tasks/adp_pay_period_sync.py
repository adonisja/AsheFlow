"""ADP pay period schedule sync for AsheFlow.

Registered in celery_app.py beat_schedule — runs weekly (Sunday 01:00 Eastern,
ahead of the 02:00 employee sync) to keep adp_pay_periods populated.

This table is a hard dependency of mismatch detection: detect_timecard_mismatches
resolves the pay period covering each timecard's work_date and skips the timecard
outright when none is found. An empty table therefore disables detection entirely
rather than degrading it (ADR-233). Nothing wrote to this table before this task
existed, so detection had never produced an adjustment.

Rows are upserted on (company_id, period_start) and never deleted —
timecard_adjustments.pay_period_id is a RESTRICT foreign key, so deleting a
referenced period would raise rather than cascade.
"""
import asyncio
import logging
from datetime import date, datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.adp_integration import ADPIntegration
from app.models.adp_pay_period import ADPPayPeriod
from app.services.adp import fetch_adp_pay_periods

logger = logging.getLogger(__name__)


def _parse_date(value) -> date | None:
    """Parse an ADP date string into a date, or None if unusable."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(value) -> datetime | None:
    """Parse an ADP datetime string into a tz-aware datetime, or None if unusable.

    ADP emits 'Z' for UTC, which fromisoformat rejects before Python 3.11.
    Naive values are assumed UTC — close_deadline is compared against
    datetime.now(timezone.utc), so a naive value would raise on comparison.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@celery_app.task(name="app.tasks.adp_pay_period_sync.sync_adp_pay_periods")
def sync_adp_pay_periods() -> dict:
    """Fetch and upsert the ADP pay period schedule for all enabled integrations.

    Every column on ADPPayPeriod is NOT NULL, so an entry missing any of
    period_start, period_end, close_deadline or pay_date is skipped and counted
    rather than written — a partial row would fail the insert and abort the whole
    company's batch.

    Returns per-company counts so the operator reviewing the first run can see
    whether ADP's schedule actually parsed, rather than inferring it from silence.

    A per-company try/except ensures one company's failure does not block others.
    """
    db = SessionLocal()
    try:
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        results = {}

        for integration in integrations:
            created = 0
            updated = 0
            skipped = 0

            try:
                pay_periods = asyncio.run(fetch_adp_pay_periods(integration))

                for entry in pay_periods:
                    adp_pay_period_id = entry.get("payPeriodID") or entry.get("payPeriodId")
                    period_start   = _parse_date(entry.get("startDate"))
                    period_end     = _parse_date(entry.get("endDate"))
                    pay_date       = _parse_date(entry.get("payDate"))
                    close_deadline = _parse_datetime(
                        entry.get("closeDeadline") or entry.get("processingDeadline")
                    )

                    if not all([adp_pay_period_id, period_start, period_end, pay_date, close_deadline]):
                        skipped += 1
                        logger.warning(
                            "ADP pay period skipped for company %s — incomplete entry "
                            "(id=%s start=%s end=%s pay_date=%s close=%s)",
                            integration.company_id, adp_pay_period_id, period_start,
                            period_end, pay_date, close_deadline,
                        )
                        continue

                    existing = db.query(ADPPayPeriod).filter(
                        ADPPayPeriod.company_id == integration.company_id,
                        ADPPayPeriod.period_start == period_start,
                    ).first()

                    if existing is None:
                        db.add(ADPPayPeriod(
                            company_id        = integration.company_id,
                            adp_pay_period_id = adp_pay_period_id,
                            period_start      = period_start,
                            period_end        = period_end,
                            close_deadline    = close_deadline,
                            pay_date          = pay_date,
                            fetched_at        = datetime.now(timezone.utc),
                        ))
                        created += 1
                    else:
                        # Upsert, never delete — timecard_adjustments.pay_period_id
                        # is a RESTRICT FK and may already reference this row.
                        existing.adp_pay_period_id = adp_pay_period_id
                        existing.period_end        = period_end
                        existing.close_deadline    = close_deadline
                        existing.pay_date          = pay_date
                        existing.fetched_at        = datetime.now(timezone.utc)
                        updated += 1

                integration.last_pay_period_sync_at = datetime.now(timezone.utc)
                db.commit()

                results[str(integration.company_id)] = {
                    "created": created, "updated": updated, "skipped": skipped,
                }
                logger.info(
                    "ADP pay period sync for company %s: %d created, %d updated, %d skipped",
                    integration.company_id, created, updated, skipped,
                )

            except Exception as e:
                db.rollback()
                logger.warning(
                    "ADP pay period sync failed for company %s: %s",
                    integration.company_id, e,
                )
                continue

        return {"status": "ok", "companies": results}

    finally:
        db.close()
