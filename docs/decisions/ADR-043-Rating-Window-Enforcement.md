# ADR-043: Rating Window Enforcement for Walker Ratings

**Date:** 2026-04-18  
**Status:** Accepted

---

## Context

Walker ratings (`POST /field-ops/rating`) had no time-gating. A driver could submit a rating for any date at any time — even days later — with no relationship to whether they had actually departed that day. This created two problems:

1. **No proof of departure**: A driver could rate a walker on a day they never left the yard.
2. **No staleness protection**: Ratings could be submitted long after the workday, when memory is unreliable and potential for retroactive manipulation exists.

---

## Decision

Gate `submit_rating` with two sequential checks:

**Gate 1 — Departure required**: Query `Departure` for `(employee_id=driver_id, date=payload.date)`. If no row exists or `departed_at` is NULL, reject with 400. A driver cannot rate walkers until they have departed.

**Gate 2 — Window still open**: Compare `now` against `departed_at + timedelta(hours=settings.rating_window_hours)`. If the window has closed, reject with 400. The window defaults to 6 hours and is configurable via `RATING_WINDOW_HOURS` in `.env`.

Both checks happen after the `driver_id` ownership check and before the same-truck and duplicate checks.

---

## Consequences

- **Accurate data**: All accepted ratings are tied to an actual departure event.
- **Bounded window**: 6-hour default covers typical workday duration + a buffer for late submission; override available for unusual shift patterns.
- **No migration required**: No schema changes — both `Departure` and `WalkerRating` tables already exist.
- **Config-driven**: `rating_window_hours` is a `pydantic_settings` field with a safe default; production can override via environment variable without code changes.

---

## Alternatives Considered

- **No gate at all** — rejected; leaves the data unreliable.
- **Date-only gate (today only)** — rejected; doesn't confirm actual departure, just calendar date.
- **Hard-coded 6-hour window** — rejected; different deployment contexts may have different shift lengths.
