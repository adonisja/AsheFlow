# Journal: Rating Window Enforcement
**Date:** 2026-04-18

---

## Context

Walker ratings had no time-gating. A driver could submit ratings without having departed, or days after the workday. This came from the discussion backlog as a data integrity item.

---

## Changes Applied

### `backend/app/core/config.py`

Added `rating_window_hours: int = 6`. No default means a missing value falls back to 6 hours. Configurable via `RATING_WINDOW_HOURS` environment variable.

### `backend/app/routers/field_ops.py`

Added `from app.core.config import settings` import at the top.

In `submit_rating`, inserted two gates after the driver ownership check:

**Gate 1 — Departure required**
```python
departure = db.query(Departure).filter(
    Departure.employee_id == payload.driver_id,
    Departure.date == payload.date,
).first()
if not departure or departure.departed_at is None:
    raise HTTPException(
        status_code=400,
        detail="Ratings can only be submitted after the driver has departed for the day.",
    )
```

**Gate 2 — Window still open**
```python
now = datetime.now(timezone.utc)
window_close = departure.departed_at + timedelta(hours=settings.rating_window_hours)
if now > window_close:
    raise HTTPException(
        status_code=400,
        detail=f"The rating window has closed. Ratings must be submitted within {settings.rating_window_hours} hours of departure.",
    )
```

Both `datetime`, `timezone`, and `timedelta` were already imported at line 1.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/core/config.py` | Added `rating_window_hours: int = 6` |
| `backend/app/routers/field_ops.py` | Added `settings` import; two departure gates in `submit_rating` |
| `docs/decisions/ADR-043-Rating-Window-Enforcement.md` | New |
