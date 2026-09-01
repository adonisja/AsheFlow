"""Response schemas for the My Stats drill-down (ADR-271).

Field names are SHORT on DayStat and stay that way. This is the payload the
client caches for up to 24 months — ~780 rows for a full-time worker — so key
names are a real fraction of the bytes. `packages_delivered` repeated 780 times
is ~8 KB of JSON keys alone.
"""
from datetime import date
from typing import Dict, List, Optional

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
    # Per-day breakdowns, folded in so the client derives every level's donut
    # and attendance without a request (ADR-271 B). Short keys: these repeat on
    # ~520 rows. `rz` is {abbreviated_rts_type: count}; `rc` is the roll-call
    # status for the day, or null if none was recorded.
    rz: Dict[str, int] = {}
    rc: Optional[str] = None

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
    # ADR-305: Optional because workforce mode returns None when NO route has
    # been Flex-scanned — an empty set has no derived delivered figure, and 0
    # would read as "delivered nothing". Always an int in full mode.
    delivered: Optional[int] = 0
    rts: int = 0
    missing: int = 0
    damaged: int = 0
    truck_damaged: int = 0
    trips: int = 0
    # ADR-305 D3. Workforce mode: routes with no Flex count, excluded from BOTH
    # delivered and attempted. > 0 means these figures cover a subset of the
    # walker's routes and the client must say so.
    routes_excluded_unscanned: int = 0
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


class BlockStatOut(BaseModel):
    """One block worked in the selected period (ADR-271 I).

    block_key survives ADR-219's address purge — it is the only geographic
    signal safe to keep indefinitely, so this carries no PII.
    """
    block_key: str
    stops: int = 0
    delivered: int = 0
    rts: int = 0
    # None, never 0.0, when nothing was attempted there.
    rts_rate: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AttendanceOut(BaseModel):
    """Roll-call outcomes for the selected period (ADR-271 I)."""
    present: int = 0
    late: int = 0
    ncns: int = 0
    total: int = 0
    # None when nothing was recorded — "no roll calls" is not "0% attendance".
    rate: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ReasonStatOut(BaseModel):
    """One RTS reason within the selected period (ADR-271 I)."""
    rts_type: str
    count: int = 0

    model_config = ConfigDict(from_attributes=True)


class PeriodExtrasOut(BaseModel):
    """Per-period extras, requested separately from the cached series.

    NOT part of the bulk payload: these are scoped to whichever period the user
    is looking at ("top 5 for week 1 may not be top 5 for the month"), so they
    cannot be precomputed for every possible period without exploding the
    response.
    """
    start_date: date
    end_date: date
    top_blocks: List[BlockStatOut] = []
    attendance: AttendanceOut = AttendanceOut()
    # Why packages came back, this period. Scoped like the counts: a driver's
    # mix covers the whole truck, a walker's covers what they carried.
    reasons: List[ReasonStatOut] = []
    # False for driver/captain: blocks come from DeliveryStop.walker_id and a
    # driver does not carry, so their list is permanently empty. The client
    # must HIDE the panel rather than render an empty one — an empty panel
    # reads as broken, not as "not applicable to you".
    blocks_apply: bool = True

    model_config = ConfigDict(from_attributes=True)


class MyStatsOut(BaseModel):
    """One request serves the entire drill-down."""
    lifetime: LifetimeTotalsOut
    # All-time, oldest first. Drives the entry-state chart.
    years: List[YearStatOut] = []
    series: StatsSeriesOut

    model_config = ConfigDict(from_attributes=True)
