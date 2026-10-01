import os
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.company import Company


def company_datetime(tz: ZoneInfo, d: date, t: time) -> datetime:
    """A wall-clock time ON a date, in `tz`, as a real UTC instant (ADR-485 D18).

    CompanyConfig stores shift_start, shift_end, checkin_open, checkin_close,
    dispatch_confirmation_cutoff and early_confirmation_deadline as naive Time
    columns, each documented as "read in the company's own timezone". Building
    rows store opens_at / closes_at / break_start / break_end the same way.

    Attaching UTC to one of those RELABELS it instead of converting it --
    07:00 New York becomes 07:00 UTC, four or five hours early depending on
    DST:

        WRONG: datetime.combine(d, t).replace(tzinfo=timezone.utc)
        WRONG: datetime.combine(d, t).astimezone(timezone.utc)   # SERVER zone
        RIGHT: company_datetime(tz, d, t)

    The second wrong form is the quieter one: `.astimezone()` on a naive value
    interprets it in the server's local zone, so it is accidentally right
    wherever the server runs UTC and silently wrong everywhere else.

    Use this for every stored Time that has to become an instant. There is no
    correct hand-rolled version.
    """
    return datetime.combine(d, t, tzinfo=tz).astimezone(timezone.utc)


def company_midnight(tz: ZoneInfo, d: date) -> datetime:
    """Start of `d` in `tz`, as a UTC instant. company_datetime with time.min.

    Spelled separately because "midnight on this date" is the commonest case
    and `time.min` at a call site reads like an implementation detail.
    """
    return company_datetime(tz, d, time.min)


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


def task_today(tz: ZoneInfo | None = None) -> date:
    """Return today's date for use in Celery tasks.

    Pass a ZoneInfo resolved from the company row (via fetch_company_timezones)
    to get the company-local date. Falls back to SERVER_TIMEZONE env var
    (default: America/New_York) when no tz is provided.
    """
    if tz is None:
        tz_str = os.environ.get("SERVER_TIMEZONE", "America/New_York")
        try:
            tz = ZoneInfo(tz_str)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def fetch_company_timezones(db: Session) -> dict:
    """Return {company_id: ZoneInfo} for all companies in one bulk query.

    Call once at the start of a Celery task, then pass tz_map.get(company_id)
    into task_today() per company — avoids N per-company DB lookups.
    """
    from app.models.company import Company
    rows = db.query(Company.id, Company.timezone).all()
    result = {}
    for company_id, tz_str in rows:
        try:
            result[company_id] = ZoneInfo(tz_str or "America/New_York")
        except ZoneInfoNotFoundError:
            result[company_id] = ZoneInfo("America/New_York")
    return result
