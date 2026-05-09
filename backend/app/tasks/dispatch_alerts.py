"""Dispatch deadline alert tasks.

Fires at 09:05 AM daily to remind dispatch that the 09:10 AM finalization
deadline is approaching. The alert is posted as a Notification to all active
dispatch/admin employees and also forwarded to the bot to post in #drivers-chat.

The actual finalization (posting to truck channels, setting permissions) is
always triggered manually by dispatch via POST /dispatch/{date}/finalize.
"""

import os
from datetime import date

import requests

from app.celery_app import celery_app
from app.database import SessionLocal
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
    today = date.today()
    db = SessionLocal()
    try:
        # Find all distinct company_ids that have a dispatch today
        company_ids = [
            row[0] for row in
            db.query(TruckAssignment.company_id)
            .filter(TruckAssignment.date == today)
            .distinct()
            .all()
        ]

        if not company_ids:
            return {"status": "skipped", "reason": "no dispatch for today", "date": str(today)}

        total_recipients = 0
        message = (
            f"⏰ Dispatch finalization deadline is at 09:10 AM. "
            f"Please confirm all assignments and click 'Finalize' to publish crew assignments to Discord. "
            f"Date: {today}"
        )

        for company_id in company_ids:
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

        db.commit()

        # Forward per-company alert to the bot
        for company_id in company_ids:
            _post_bot_alert(str(today), message, str(company_id))

        return {
            "status": "alerted",
            "date": str(today),
            "recipients": total_recipients,
            "companies": len(company_ids),
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
