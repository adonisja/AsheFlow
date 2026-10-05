"""Dispatch deadline alert tasks.

Fires at 09:05 AM daily to remind dispatch that the finalization deadline is
approaching, naming the trucks that are still unfinalized. The deadline comes
from CompanyConfig.dispatch_confirmation_cutoff, read in the company's own
timezone (ADR-486) — the message used to hardcode "09:10 AM", which was wrong for
any tenant that changed it.

Skips a company with nothing outstanding. The previous version asked only whether
ANY assignment existed today, so a dispatcher who had finalised everything at
08:00 was still told to go and finalise.

The alert is posted as a Notification to all active dispatch/admin employees and
also forwarded to the bot to post in #drivers-chat.

The actual finalization (posting to truck channels, setting permissions) is
always triggered manually by dispatch via POST /dispatch/{date}/finalize.
"""

import os
import requests

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import (
    company_datetime,
    fetch_company_timezones,
    task_today,
)
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.services.company_config import get_company_config
from app.services.notify import write_notification


@celery_app.task(name="app.tasks.dispatch_alerts.alert_finalization_deadline")
def alert_finalization_deadline() -> dict:
    """Runs at 09:05 AM daily.

    For each company that has a dispatch scheduled today:
    1. Fires an in-app Notification to all active dispatch/admin employees.
    2. Forwards an alert to the bot to post in that company's #drivers-chat.

    Returns a summary dict.
    """
    db = SessionLocal()
    try:
        tz_map = fetch_company_timezones(db)
        total_recipients = 0
        alerted_companies = []

        for company_id, tz in tz_map.items():
            today = task_today(tz)

            # ADR-487 D2/D10 fixed THREE defects in this block.
            #
            # 1. The query asked whether ANY assignment exists today
            #    (`.first()`), so it could not name the trucks — and a
            #    dispatcher who finalised everything at 08:00 was still told to
            #    go and finalise. It now selects the UNFINALIZED ones
            #    (`status != 'completed'`, the marker finalize_dispatch sets)
            #    and skips the company when none are outstanding.
            #
            # 2. The message hardcoded "09:10 AM" while
            #    CompanyConfig.dispatch_confirmation_cutoff is a configurable
            #    Time. Any tenant that changed it was told the wrong deadline.
            #
            # 3. That cutoff is a naive Time documented as "read in the
            #    company's own timezone", so it is rendered through
            #    company_datetime (ADR-486) rather than formatted directly.
            #
            # "A reminder that does not say which truck is a reminder you have
            # to go and check."
            unfinalized = (
                db.query(Truck.name)
                .join(TruckAssignment, TruckAssignment.truck_id == Truck.id)
                .filter(
                    TruckAssignment.company_id == company_id,
                    TruckAssignment.date == today,
                    TruckAssignment.status != "completed",
                    Truck.company_id == company_id,
                )
                .order_by(Truck.name)
                .all()
            )
            if not unfinalized:
                continue

            truck_names = [n for (n,) in unfinalized]
            # Capped: a station with thirty outstanding trucks needs a count,
            # not thirty names in a notification body.
            shown = ", ".join(truck_names[:8])
            if len(truck_names) > 8:
                shown += f" …and {len(truck_names) - 8} more"

            cfg = get_company_config(db, company_id)
            cutoff = getattr(cfg, "dispatch_confirmation_cutoff", None)
            if cutoff is not None:
                deadline = company_datetime(tz, today, cutoff).astimezone(tz)
                # lstrip("0") rather than %-I: that is a glibc/BSD extension,
                # not standard, and raises on a musl-based image. The strip is
                # safe because %I is always two digits, 01-12.
                when = f"at {deadline.strftime('%I:%M %p').lstrip('0')}"
            else:
                # No configured cutoff. Saying "at None" is worse than saying
                # nothing, and inventing 09:10 is the defect being fixed.
                when = "soon"

            noun = "truck" if len(truck_names) == 1 else "trucks"
            message = (
                f"⏰ Dispatch finalization deadline is {when}. "
                f"{len(truck_names)} {noun} not finalized: {shown}. "
                f"Confirm the assignments and click 'Finalize' to publish crew "
                f"assignments to Discord. Date: {today}"
            )

            recipients = db.query(Employee).filter(
                Employee.company_id == company_id,
                Employee.role.in_(["dispatch", "admin"]),
                Employee.is_active == True,
            ).all()

            for emp in recipients:
                write_notification(
                    db,
                    company_id=company_id,
                    employee_id=emp.id,
                    type="dispatch_finalization_reminder",
                    message=message,
                )

            total_recipients += len(recipients)
            alerted_companies.append((company_id, today, message))

        db.commit()

        for company_id, today, message in alerted_companies:
            _post_bot_alert(str(today), message, str(company_id))

        if not alerted_companies:
            return {"status": "skipped", "reason": "no dispatch for today across any company"}

        return {
            "status": "alerted",
            "recipients": total_recipients,
            "companies": len(alerted_companies),
        }
    finally:
        db.close()


def _post_bot_alert(dispatch_date: str, message: str, company_id: str) -> None:
    """Best-effort POST to the bot's internal alert endpoint.

    Non-blocking — logged on failure but does not raise so the Celery task
    doesn't retry on a bot connectivity issue.
    """
    import logging
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        requests.post(
            f"{bot_url}/internal/alert",
            json={"date": dispatch_date, "message": message, "company_id": company_id},
            headers={"X-Internal-Secret": secret},
            timeout=3,
        )
    except Exception as e:
        logging.getLogger(__name__).warning("Could not reach bot for alert (company %s): %s", company_id, e)
