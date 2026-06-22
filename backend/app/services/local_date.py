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
