from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.company import Company


def company_today(db: Session, company_id) -> date:
    """Return today's date in the company's configured timezone.

    Falls back to UTC if the timezone string is invalid or the company has
    no Company row. Always prefer this over date.today() in any endpoint
    that gates on 'today' (dispatch, field ops, shift sessions, etc.).
    """
    tz_str = "UTC"
    company = db.query(Company).filter(
        Company.id == company_id
    ).first()
    if company and company.timezone:
        tz_str = company.timezone
    try:
        tz = ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        tz = timezone.utc  # type: ignore[assignment]
    return datetime.now(tz).date()
