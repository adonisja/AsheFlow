"""Dispatch deadline alert tasks.

Fires at 09:05 AM daily to remind dispatch that the 09:10 AM finalization
deadline is approaching. The alert is posted as a Notification to all active
dispatch/admin employees and also forwarded to the bot to post in #drivers-chat.

The actual finalization (posting to truck channels, setting permissions) is
always triggered manually by dispatch via POST /dispatch/{date}/finalize.
"""

import os
import requests

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import task_today, fetch_company_timezones
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck_assignment import TruckAssignment


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

            has_dispatch = db.query(TruckAssignment).filter(
                TruckAssignment.company_id == company_id,
                TruckAssignment.date == today,
            ).first()
            if not has_dispatch:
                continue

            message = (
                f"⏰ Dispatch finalization deadline is at 09:10 AM. "
                f"Please confirm all assignments and click 'Finalize' to publish crew assignments to Discord. "
                f"Date: {today}"
            )

            recipients = db.query(Employee).filter(
                Employee.company_id == company_id,
                Employee.role.in_(["dispatch", "admin"]),
                Employee.is_active == True,
            ).all()

            for emp in recipients:
                db.add(Notification(
                    company_id=company_id,
                    employee_id=emp.id,
                    type="dispatch_finalization_reminder",
                    message=message,
                ))

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
