"""Dispatch deadline alert tasks.

Fires at 09:05 AM daily to remind dispatch that the 09:10 AM finalization
deadline is approaching. The alert is posted as a Notification to all active
dispatch/admin employees and also forwarded to the bot to post in #drivers-chat.

The actual finalization (posting to truck channels, setting permissions) is
always triggered manually by dispatch via POST /dispatch/{date}/finalize.
"""

import os
from datetime import date, datetime, timezone

import aiohttp

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck_assignment import TruckAssignment


@celery_app.task(name="app.tasks.dispatch_alerts.alert_finalization_deadline")
def alert_finalization_deadline() -> dict:
    """Runs at 09:05 AM daily.

    1. Checks if a dispatch exists for today.
    2. If yes, fires an in-app Notification to all active dispatch/admin employees.
    3. Forwards an alert to the bot to post in #drivers-chat.

    Returns a summary dict.
    """
    today = date.today()
    db = SessionLocal()
    try:
        has_dispatch = db.query(TruckAssignment).filter(
            TruckAssignment.date == today
        ).first()

        if not has_dispatch:
            return {"status": "skipped", "reason": "no dispatch for today", "date": str(today)}

        recipients = db.query(Employee).filter(
            Employee.role.in_(["dispatch", "admin"]),
            Employee.is_active == True,
        ).all()

        message = (
            f"⏰ Dispatch finalization deadline is at 09:10 AM. "
            f"Please confirm all assignments and click 'Finalize' to publish crew assignments to Discord. "
            f"Date: {today}"
        )

        for emp in recipients:
            db.add(Notification(
                employee_id=emp.id,
                type="dispatch_finalization_reminder",
                message=message,
            ))

        db.commit()

        # Forward to bot for #drivers-chat post
        _post_bot_alert(str(today), message)

        return {
            "status": "alerted",
            "date": str(today),
            "recipients": len(recipients),
        }
    finally:
        db.close()


def _post_bot_alert(dispatch_date: str, message: str) -> None:
    """Best-effort POST to the bot's internal alert endpoint.

    Non-blocking — logged on failure but does not raise so the Celery task
    doesn't retry on a bot connectivity issue.
    """
    import requests
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        requests.post(
            f"{bot_url}/internal/alert",
            json={"date": dispatch_date, "message": message},
            headers={"X-Internal-Secret": secret},
            timeout=3,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not reach bot for alert: %s", e)
