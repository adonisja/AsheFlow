import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.company import Company


def company_tz(db: Session, company_id) -> ZoneInfo:
    """Return the ZoneInfo for the company's configured timezone, falling back to UTC."""
    tz_str = "UTC"
    company = db.query(Company).filter(Company.id == company_id).first()
    if company and company.timezone:
        tz_str = company.timezone
    try:
        return ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def company_today(db: Session, company_id) -> date:
    """Return today's date in the company's configured timezone.

    Falls back to UTC if the timezone string is invalid or the company has
    no Company row. Always prefer this over date.today() in any endpoint
    that gates on 'today' (dispatch, field ops, shift sessions, etc.).
    """
    return datetime.now(company_tz(db, company_id)).date()


def task_today() -> date:
    """Return today's date for use in Celery tasks that have no caller/company_id.

    Reads SERVER_TIMEZONE from the environment (default: America/New_York).
    Use this instead of date.today() in all scheduled tasks — date.today()
    returns the server's UTC date which is wrong after ~7 PM Eastern.
    """
    tz_str = os.environ.get("SERVER_TIMEZONE", "America/New_York")
    try:
        tz = ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()
