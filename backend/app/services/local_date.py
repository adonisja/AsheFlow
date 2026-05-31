from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.company import CompanyConfig


def company_today(db: Session, company_id) -> date:
    """Return today's date in the company's configured timezone.

    Falls back to UTC if the timezone string is invalid or the company has
    no config row. Always prefer this over date.today() in any endpoint
    that gates on 'today' (dispatch, field ops, shift sessions, etc.).
    """
    tz_str = "UTC"
    config = db.query(CompanyConfig).filter(
        CompanyConfig.company_id == company_id
    ).first()
    if config and config.timezone:
        tz_str = config.timezone
    try:
        tz = ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        tz = timezone.utc  # type: ignore[assignment]
    return datetime.now(tz).date()
