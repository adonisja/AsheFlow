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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.building_taxonomy import BUILDING_TYPES, OTHER, validate_workloads


class CollectedProfileIn(BaseModel):
    """One building profile as submitted from the public page."""
    model_config = ConfigDict(extra="forbid")

    address:        str = Field(..., min_length=3, max_length=200)
    building_type:  str = Field(..., max_length=40)

    # ADR-418. `building_category` is deliberately ABSENT from the request: it
    # is derived from building_type server-side. Accepting it would let a client
    # send residential/loading_dock, and a stored contradiction is worse than a
    # lookup.
    has_security_desk: bool = False

    # Multi-select, and REQUIRED to be non-empty — ["not_applicable"] is how a
    # collector says "none of these", which is a different statement from an
    # unanswered field. max_length caps it at the tag count so a client cannot
    # send the same tag a thousand times.
    workloads: list[str] = Field(..., min_length=1, max_length=5)

    # ADR-419. Required when `other` is picked and forbidden otherwise — see
    # the model validator. Bounded like every other free-text field at this
    # trust boundary.
    workload_other: Optional[str] = Field(None, max_length=200)

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

    @model_validator(mode="after")
    def _workloads_agree_with_the_type(self):
        """Cross-field rules, which a per-field validator cannot see.

        Two of them:
          - A walk-up is neither a high-rise nor a bulk drop (ADR-419). Checked
            here because it needs BOTH fields.
          - `other` means the four tags do not fit, so it must come with the
            text that says what does; and text without the tag is a value no
            reader would ever look at.
        """
        validate_workloads(self.workloads, self.building_type)

        has_other = OTHER in self.workloads
        text = (self.workload_other or "").strip()
        if has_other and not text:
            raise ValueError("Pick 'other' and say what it is.")
        if text and not has_other:
            raise ValueError("workload_other is only meaningful with the 'other' tag.")
        return self

    @field_validator("workloads")
    @classmethod
    def _known_workloads(cls, v: list[str]) -> list[str]:
        # Shape only. The rules that need another field (walk-up exclusivity,
        # `other` requiring its text) are in the model validator above, which
        # runs after every field is populated.
        validate_workloads(v)
        # De-duplicated but ORDER PRESERVED: the set of tags is what matters,
        # and sorting would discard the order the collector picked them in for
        # no gain.
        seen: set[str] = set()
        return [t for t in v if not (t in seen or seen.add(t))]

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

    # ADR-426. Which device is submitting, so a collector can correct their own
    # entry after a door locks. Optional: a client that does not send one simply
    # cannot edit, which is the pre-ADR-426 behaviour.
    #
    # NOT trusted as an identity. It decides one thing — whether this row is
    # yours to update — and the worst a forged value achieves is overwriting a
    # row whose device_id the forger already knew, which is not a secret worth
    # more than the row itself.
    device_id: Optional[str] = Field(None, min_length=8, max_length=64)


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

    # ADR-426. Rows this device already owned and has now corrected. Reported
    # apart from `accepted` so a collector can tell "I added two doors" from
    # "I fixed the one I got wrong".
    updated: int = 0


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

    # ADR-426. Optional: without it the answer is simply "is this door locked
    # for anyone", which is the pre-ADR-426 behaviour.
    device_id: Optional[str] = Field(None, min_length=8, max_length=64)


TOP_COLLECTORS = 3
"""How many collectors the campaign ranking shows (ADR-427).

Three, because it is an encouragement rather than a scoreboard: a longer list
tells the person in eleventh place exactly where they stand, which is not the
point.
"""

VERIFICATION_LIMIT = 2
"""How many independent observations a door may collect before it is closed.

Two, because the point is VERIFICATION: a second collector either confirms the
first or disagrees with them, and both outcomes are informative. A third adds
cost (someone walks to a door that is already answered twice) without adding
information, so the door locks.
"""


class CollectionCheckOut(BaseModel):
    """A count, a date, and whether the door is closed.

    `collected_on` is included because "already done" is far more convincing
    with a date on it, and it reveals nothing the bit did not: the caller
    already knows the address and already knows it was collected.

    Nothing else. Not who collected it, not the building type, not an id —
    those would make this a read path for the record rather than a check for
    its existence.
    """
    known:        bool
    collected_on: Optional[date] = None

    # ADR-420. How many observations this campaign already has for the door,
    # and whether that has reached the limit.
    #
    # A COUNT, not just a bit, is a wider disclosure than the original check —
    # but only by "how many times", about an address the caller already named
    # and already knows is collected. It buys the thing the bit could not: a
    # collector can be told "one more needed" instead of being turned away from
    # a door that still wants verifying.
    count:  int  = 0
    # NOT locked to a device that already owns a row here — see check_address.
    locked: bool = False
    # ADR-426. This device has already submitted this door, so re-submitting
    # updates its row. Lets the form say "you recorded this" rather than
    # "someone did".
    mine:   bool = False


class LeaderboardEntryOut(BaseModel):
    """One collector's standing in a campaign (ADR-427).

    A HANDLE and a COUNT. Not the addresses they collected, not when, not which
    device — a ranking needs neither, and a public endpoint returning more
    would be describing the table rather than summarising it.
    """
    handle: str
    count:  int


class LeaderboardIn(BaseModel):
    """Ask for a campaign's top collectors."""
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=16, max_length=64)


class CollectionTokenCreate(BaseModel):
    """Operator-side, authenticated. Issues a campaign token."""
    model_config = ConfigDict(extra="forbid")

    label:      str = Field(..., min_length=1, max_length=120)
    daily_cap:  int = Field(500, ge=1, le=5000)
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)

    # ADR-423. Deliberately ABSENT: `scope` and `company_id` are decided by WHO
    # is calling, not by what they ask for. A super admin creates an open
    # campaign; a company admin creates one bound to their own company. Letting
    # the body choose would let a company admin mint an open campaign, which is
    # precisely the boundary this ADR draws.


# ADR-423. Who may submit under a campaign.
#
# OPEN     — anyone with the link. Super admin only: it collects across tenants
#            and its rows carry no company_id, so no company admin can read it.
# COMPANY  — an authenticated employee of the owning company. The link is not
#            enough; this is the Driver Survey model, scoped to a staff pool.
SCOPE_OPEN = "open"
SCOPE_COMPANY = "company"
SCOPES = frozenset({SCOPE_OPEN, SCOPE_COMPANY})


class CollectionTokenOut(BaseModel):
    """The token is returned ONCE, at creation. It is not readable afterwards —
    a listing that echoed live secrets would turn one leaked page into all of
    them."""
    model_config = ConfigDict(from_attributes=True)

    id:         UUID
    label:      str
    daily_cap:  int
    created_at: object
    scope:      str
    company_id: Optional[UUID] = None
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
    # ADR-424. NULL for an open campaign. ADR-423 made the COLUMN nullable and
    # left this read schema declaring a bare UUID, so the first profile
    # submitted to an open campaign 500'd the super-admin listing on
    # `model_validate` — and a 500 carries no CORS headers, so the browser
    # reported it as a CORS failure rather than a server error.
    company_id:     Optional[UUID]
    token_id:       UUID
    address:           str
    # ADR-430. The folded comparison key, so the reader can group the rows that
    # describe ONE door. Derived from an address the reader is already looking
    # at, so it discloses nothing the row did not.
    door_key:          str
    # How many observations that door has across the WHOLE campaign, and
    # whether that closes it to new collectors (ADR-420).
    #
    # Computed server-side rather than by counting the rows on screen: the
    # listing is paged, so a door whose second observation falls on the next
    # page would count as one and read as still open. A count that is right
    # only for small campaigns is worse than no count.
    observations:      int = 1
    closed:            bool = False
    building_type:     str
    building_category: str
    has_security_desk: bool
    workloads:         list[str]
    workload_other:    Optional[str]
    workload_class:    str
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
    """A campaign, how much has arrived under it, and its link.

    ADR-424 REVERSES ADR-415's "returned once at creation and never again".

    That rule treated the token as a password. It is not: an OPEN campaign's
    link is handed to a dozen collectors by design, pasted into group chats and
    typed off a phone screen — it is a shared URL, closer to a Google Doc
    "anyone with the link" than to a credential. Withholding it from the one
    person authorised to manage campaigns protected nothing while guaranteeing
    that a mislaid link meant revoking and re-issuing to everyone who had it.

    The original worry — one compromised admin session exposing every campaign
    — is real but was already true: that session can CREATE campaigns, revoke
    them, and read every collected address. A listing that also shows the links
    adds nothing an attacker could not already do, and the gate that matters
    (`_scope_reads`: super admin sees all, a company admin sees only their own)
    is unchanged.
    """
    model_config = ConfigDict(from_attributes=True)

    id:          UUID
    # NULL for an open campaign (ADR-423).
    company_id:  Optional[UUID]
    scope:       str
    label:       str
    daily_cap:   int
    revoked_at:  Optional[object]
    expires_at:  Optional[object]
    created_at:  object
    created_by_name: Optional[str]
    submission_count: int = 0

    # ADR-424. The link, so it can be re-copied. A revoked campaign returns
    # None: its link no longer works, and showing a dead string invites someone
    # to send it.
    token: Optional[str] = None
