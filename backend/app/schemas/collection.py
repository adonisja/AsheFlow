"""Request/response shapes for public collection (ADR-415).

DIMENSION 9 APPLIES HERE MORE THAN ANYWHERE. Every other request schema in this
codebase is filled in by someone who authenticated first; this one is filled in
by anybody who has the URL. Every field is concretely typed, bounded, and
`extra="forbid"` — an unrecognised key is a client bug worth a 422, not
something to persist silently.
"""
from __future__ import annotations

from datetime import date, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.location_profile import BUILDING_TYPES, WORKLOAD_CLASSES


class CollectedProfileIn(BaseModel):
    """One building profile as submitted from the public page."""
    model_config = ConfigDict(extra="forbid")

    address:        str = Field(..., min_length=3, max_length=200)
    building_type:  str = Field(..., max_length=30)
    workload_class: str = Field(..., max_length=20)

    note:         Optional[str]  = Field(None, max_length=2000)
    opens_at:     Optional[time] = None
    closes_at:    Optional[time] = None
    break_start:  Optional[time] = None
    break_end:    Optional[time] = None
    troublesome:  bool           = False
    collected_by: Optional[str]  = Field(None, max_length=100)
    collected_on: date

    @field_validator("building_type")
    @classmethod
    def _known_building_type(cls, v: str) -> str:
        # Validated against the SAME frozenset the sort pipeline reads. A value
        # this endpoint accepted but the rest of the system rejects would sit in
        # the table looking like data and promote into nothing.
        if v not in BUILDING_TYPES:
            raise ValueError(f"Unknown building_type: {v!r}")
        return v

    @field_validator("workload_class")
    @classmethod
    def _known_workload(cls, v: str) -> str:
        if v not in WORKLOAD_CLASSES:
            raise ValueError(f"Unknown workload_class: {v!r}")
        return v

    @field_validator("address", "note", "collected_by")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v


class CollectionSubmitIn(BaseModel):
    """A batch of profiles for one campaign.

    A batch rather than one-at-a-time because the page is used offline: a
    collector fills in six buildings with no signal and submits when they have
    one. Capped at 100 — enough for a full day, small enough that one request
    cannot be used as a bulk-write primitive.

    NOTE the absence of company_id. It is resolved from the token server-side
    (ADR-415 D2); accepting it here would be a cross-tenant write.
    """
    model_config = ConfigDict(extra="forbid")

    token:    str = Field(..., min_length=16, max_length=64)
    profiles: list[CollectedProfileIn] = Field(..., min_length=1, max_length=100)


class CollectionSubmitOut(BaseModel):
    """What the submitter is told.

    Deliberately thin. It confirms receipt and nothing else — no ids, no listing,
    no lookup, no indication of what else is in the table. A public endpoint's
    response is an information-disclosure surface (ADR-415 D4).

    `duplicate_addresses` is the one echo, and it is NOT a read path. It returns
    only addresses present in THIS request that the campaign had already
    received — data the submitter supplied and already holds. It supports no
    enumeration: you cannot learn whether an address is known without already
    knowing the address and submitting a complete profile for it, which costs a
    row against the daily cap.

    It exists because the alternative is worse for privacy, not better. Without
    it a collector re-profiles a building someone else already did, discovers
    this from a bare count after the typing is done, and keeps doing it —
    every wasted visit being another person standing at a real door.
    """
    accepted:  int
    duplicate: int
    duplicate_addresses: list[str] = []


class CollectionCheckIn(BaseModel):
    """Ask whether one address is already collected under this campaign.

    ONE address per call, deliberately. A list parameter would turn this into a
    bulk oracle: paste a thousand addresses, learn the campaign's whole
    coverage in one request. One-at-a-time plus the rate limit makes mapping
    the campaign slow enough to be pointless, while costing a collector nothing
    — they check one door because they are standing at one door.
    """
    model_config = ConfigDict(extra="forbid")

    token:   str = Field(..., min_length=16, max_length=64)
    address: str = Field(..., min_length=3, max_length=200)


class CollectionCheckOut(BaseModel):
    """One bit, and the date if it is set.

    `collected_on` is included because "already done" is far more convincing
    with a date on it, and it reveals nothing the bit did not: the caller
    already knows the address and already knows it was collected.

    Nothing else. Not who collected it, not the building type, not an id —
    those would make this a read path for the record rather than a check for
    its existence.
    """
    known:        bool
    collected_on: Optional[date] = None


class CollectionTokenCreate(BaseModel):
    """Operator-side, authenticated. Issues a campaign token."""
    model_config = ConfigDict(extra="forbid")

    label:      str = Field(..., min_length=1, max_length=120)
    daily_cap:  int = Field(500, ge=1, le=5000)
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)


class CollectionTokenOut(BaseModel):
    """The token is returned ONCE, at creation. It is not readable afterwards —
    a listing that echoed live secrets would turn one leaked page into all of
    them."""
    model_config = ConfigDict(from_attributes=True)

    id:         UUID
    label:      str
    daily_cap:  int
    created_at: object
    token:      Optional[str] = None


# ── Super-admin read (ADR-415 addendum) ──────────────────────────────────────

class CollectedProfileOut(BaseModel):
    """One collected profile, as the platform owner sees it.

    GATED ON `get_super_admin`, NOT `get_platform_staff`. These rows are customer
    delivery addresses, and ADR-343 D4 forbids any `platform_support` endpoint
    from returning addresses or personal data — a support login must not become
    a cross-tenant PII surface. The owner reading their own collected data is a
    different principal from staff diagnosing a ticket.
    """
    model_config = ConfigDict(from_attributes=True)

    id:             UUID
    company_id:     UUID
    token_id:       UUID
    address:        str
    building_type:  str
    workload_class: str
    note:           Optional[str]
    opens_at:       Optional[time]
    closes_at:      Optional[time]
    break_start:    Optional[time]
    break_end:      Optional[time]
    troublesome:    bool
    collected_by:   Optional[str]
    collected_on:   date
    submitted_at:   object
    review_status:  str


class CollectionTokenSummary(BaseModel):
    """A campaign and how much has arrived under it.

    `token` is deliberately ABSENT. The secret is returned once at creation and
    never again; a listing that echoed live tokens would turn one compromised
    admin session into every campaign at once.
    """
    model_config = ConfigDict(from_attributes=True)

    id:          UUID
    company_id:  UUID
    label:       str
    daily_cap:   int
    revoked_at:  Optional[object]
    expires_at:  Optional[object]
    created_at:  object
    created_by_name: Optional[str]
    submission_count: int = 0
