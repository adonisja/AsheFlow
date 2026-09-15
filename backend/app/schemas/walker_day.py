"""The route log's submission shape (ADR-417 D3).

DIMENSION 9 AT EVERY LEVEL. The payload is stored as JSONB, which is exactly
the situation the rule was written for: a `Dict[str, Any]` here would be
accepted unvalidated, persisted verbatim, and echoed back into a UI. Every
nested object is its own BaseModel with `extra="forbid"`, every string is
bounded, every list is bounded, every count has `ge=`.

The shapes mirror `frontend/src/utils/walkerLogDb.ts`. Hand-maintained — there
is no codegen — so a field added there must be added here or the collector's
submission is rejected with a 422 naming the key.

WHY JSONB AND NOT FIVE TABLES. This is research data with one reader and a CSV
as its output. Normalising day -> route -> tote -> address, plus RTS and OVs,
would buy join performance nobody needs and cost a migration every time the
field log grows a column — which it has done three times this month.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirrors DIFFICULTIES and OV_SIZES in walkerLogDb.ts.
DIFFICULTIES = frozenset({"easy", "moderate", "hard", "brutal"})
OV_SIZES = frozenset({"XS", "S", "M", "L", "XL"})

# "HH:MM" or empty. Times are local to the station and paired with the day's
# date; storing a tz-aware timestamp would imply a precision the collector's
# wristwatch does not have.
_TIME = r"^([01]\d|2[0-3]):[0-5]\d$|^$"


class RTSIn(BaseModel):
    """One package returned to station."""
    model_config = ConfigDict(extra="forbid")

    tba:    str = Field("", max_length=40)
    code:   str = Field("", max_length=20)
    reason: str = Field("", max_length=300)


class OVIn(BaseModel):
    """One oversized package carried on a route."""
    model_config = ConfigDict(extra="forbid")

    ov_id:     str = Field("", max_length=40)
    size:      str = Field("", max_length=2)
    address:   str = Field("", max_length=200)
    sort_zone: str = Field("", max_length=20)

    @field_validator("size")
    @classmethod
    def _known_size(cls, v: str) -> str:
        # Empty is allowed: a collector who did not record the size should not
        # be forced to invent one.
        if v and v not in OV_SIZES:
            raise ValueError(f"Unknown OV size: {v!r}")
        return v


class ToteIn(BaseModel):
    """One tote, and the addresses it carried."""
    model_config = ConfigDict(extra="forbid")

    bag_id:    str = Field(..., min_length=1, max_length=40)
    # 60 addresses is already a very full tote; the cap exists so one request
    # cannot be used as a bulk-write primitive, not to constrain real work.
    addresses: list[str] = Field(default_factory=list, max_length=60)

    sort_zone: Optional[str] = Field(None, max_length=20)
    stop:      Optional[str] = Field(None, max_length=20)

    stop_package_count: Optional[int] = Field(None, ge=0, le=10_000)
    stop_ov_count:      Optional[int] = Field(None, ge=0, le=1_000)
    stop_bag_count:     Optional[int] = Field(None, ge=0, le=1_000)

    @field_validator("addresses")
    @classmethod
    def _bounded_addresses(cls, v: list[str]) -> list[str]:
        # Bounded per item as well as per list: max_length on the list caps the
        # count, not the size of each entry.
        for a in v:
            if len(a) > 200:
                raise ValueError("An address is longer than 200 characters.")
        return v


class RouteIn(BaseModel):
    """One route a walker carried."""
    model_config = ConfigDict(extra="forbid")

    # Day-wide unique, not a per-walker counter (see LogRoute in walkerLogDb.ts).
    route_id: int = Field(..., ge=1, le=100_000)

    totes: list[ToteIn] = Field(default_factory=list, max_length=60)
    ovs:   list[OVIn]   = Field(default_factory=list, max_length=60)
    rts:   list[RTSIn]  = Field(default_factory=list, max_length=200)

    route_start: str = Field("", pattern=_TIME)
    route_end:   str = Field("", pattern=_TIME)

    difficulty: str = Field("", max_length=10)
    notes:      str = Field("", max_length=2000)

    @field_validator("difficulty")
    @classmethod
    def _known_difficulty(cls, v: str) -> str:
        if v and v not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty: {v!r}")
        return v


class WalkerDayIn(BaseModel):
    """One walker's whole day."""
    model_config = ConfigDict(extra="forbid")

    # As typed. ADR-417 D3: names are the point of this data and are stored
    # verbatim, deliberately and temporarily.
    walker_name: str = Field(..., min_length=1, max_length=100)
    collected_on: date

    arrival_time:   str = Field("", pattern=_TIME)
    departure_time: str = Field("", pattern=_TIME)

    routes: list[RouteIn] = Field(default_factory=list, max_length=40)

    # NOT `id` or `updated_at` from the client: the id is derived server-side
    # from (token, date, walker) so a client cannot address another row, and
    # the timestamp is the server's to set.


class WalkerDaySubmitIn(BaseModel):
    """A batch of days for one campaign.

    Batched for the same reason addresses are: the page is used offline and a
    collector submits several days when they next have signal.
    """
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=16, max_length=64)
    days:  list[WalkerDayIn] = Field(..., min_length=1, max_length=40)


class WalkerDaySubmitOut(BaseModel):
    """Receipt only.

    `replaced` is the count of days that already existed and were overwritten
    (ADR-417 D5 — last write wins). It tells a collector their retry landed,
    without describing anything else in the table.
    """
    accepted: int
    replaced: int


# ── Super-admin read (ADR-417 D3) ────────────────────────────────────────────

class CollectedWalkerDayOut(BaseModel):
    """One logged day, as the platform owner sees it.

    GATED ON `get_super_admin`, NOT `get_platform_staff` — the same rule as
    ADR-415 D6, and for a stronger reason here: this carries real coworkers'
    NAMES. ADR-343 D4 forbids any `platform_support` endpoint from returning
    personal data, and a support login is cross-tenant.
    """
    model_config = ConfigDict(from_attributes=True)

    id:           object
    company_id:   object
    token_id:     object
    walker_name:  str
    collected_on: date

    arrival_time:   Optional[str]
    departure_time: Optional[str]

    route_count: int
    tote_count:  int
    rts_count:   int

    submitted_at: object
    revision:     int


class CollectedWalkerDayDetail(CollectedWalkerDayOut):
    """The listing row plus the whole day.

    Separate from the listing model so the payloads are not shipped by default:
    a page of forty days with every tote and address inline is a large response
    over a phone connection, and the listing only needs the counts.
    """
    payload: dict
