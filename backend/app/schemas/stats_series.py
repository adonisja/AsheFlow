"""Response schemas for the My Stats drill-down (ADR-271).

Field names are SHORT on DayStat and stay that way. This is the payload the
client caches for up to 24 months — ~780 rows for a full-time worker — so key
names are a real fraction of the bytes. `packages_delivered` repeated 780 times
is ~8 KB of JSON keys alone.
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class DayStatOut(BaseModel):
    """One completed day. Never today — see StatsSeriesOut.end_date."""
    d: date
    delivered: int = 0
    total: int = 0
    rts: int = 0
    missing: int = 0
    # Packages this person brought back DAMAGED. A SUBSET of `rts`, since
    # package_damaged is one of the six RTS_TYPES — never add the two.
    damaged: int = 0
    # Damage reported on their truck before delivery (station_sort/truck_load/
    # in_truck). A different event from `damaged`; the UI must not sum them.
    truck_damaged: int = 0
    effort: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StatsSeriesOut(BaseModel):
    """The whole cacheable series, oldest first.

    IMMUTABLE ONCE FETCHED: `end_date` is always yesterday, so nothing in this
    payload can change after it is served. That is what makes client-side
    caching and on-device aggregation safe — the client groups these days into
    weeks, months and years itself rather than asking the server four times.
    """
    start_date: date
    end_date: date
    role: str
    days: List[DayStatOut] = []

    model_config = ConfigDict(from_attributes=True)


class LifetimeTotalsOut(BaseModel):
    """Header figures — ALL TIME, deliberately not windowed to the series.

    A 'lifetime' total that silently meant 'the last 24 months' would be a lie,
    so these are computed separately.
    """
    delivered: int = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0
    trips: int = 0
    # Null, never 0.0, when nothing has been attempted: "no data" and "0%
    # success" are different facts and must not render identically.
    success_pct: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class YearStatOut(BaseModel):
    """One calendar year, all time.

    Separate from the daily series because that series is capped at 24 months
    and the LIFETIME chart is year-over-year (ADR-271 D2).
    """
    year: int
    delivered: int = 0
    total: int = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0

    model_config = ConfigDict(from_attributes=True)


class MyStatsOut(BaseModel):
    """One request serves the entire drill-down."""
    lifetime: LifetimeTotalsOut
    # All-time, oldest first. Drives the entry-state chart.
    years: List[YearStatOut] = []
    series: StatsSeriesOut

    model_config = ConfigDict(from_attributes=True)
