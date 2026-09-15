"""Public data collection — a quarantine lane, not an intake path (ADR-415).

Coworkers collect building profiles on their own phones at a public URL and
submit them here. The submitter has no account, no session, and no tenant
context, which makes this the only write path in the system with no
`caller.company_id` to scope by.

WHY A SEPARATE TABLE RATHER THAN `building_profiles` (ADR-415 D1)
-----------------------------------------------------------------
`BuildingProfile` feeds the sort algorithm's weighted effort score and the
walker's UI at the door. An anonymous writer reaching it could change how a real
tenant's routes are built. Landing here instead makes the worst case "a research
table full of junk" rather than "dispatch mis-routed all morning".

Promotion from here into `building_profiles` is a separate, AUTHENTICATED action
by someone who can see what arrived — that is where the usual RoleChecker gates
apply, unchanged.

NOTHING READS THIS TABLE except that review. It is not trusted data.
"""
import uuid

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class CollectionToken(Base):
    """An opaque, revocable key naming a collection campaign.

    NOT AUTHENTICATION (ADR-415 D2). It identifies no person, grants no read
    access, and its compromise costs exactly one polluted collection table. What
    it buys is attribution — which campaign did this arrive for — and a kill
    switch, without provisioning accounts for people helping out for a week.

    `company_id` is resolved FROM the token server-side. A public endpoint that
    accepted a tenant id in its body would be a cross-tenant write waiting to
    happen, so the body never carries one.
    """
    __tablename__ = "collection_tokens"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)

    # The secret itself. Compared in full; never logged, never returned after
    # creation. Long enough that guessing is not a threat model.
    token       = Column(String(64), nullable=False, unique=True, index=True)

    # What this campaign is for, so a table of submissions can be read months
    # later without archaeology.
    label       = Column(String(120), nullable=False)

    # Revocation and expiry are separate levers: revoked is a decision, expired
    # is a deadline. Both stop submissions; only one implies something happened.
    revoked_at  = Column(DateTime(timezone=True), nullable=True)
    expires_at  = Column(DateTime(timezone=True), nullable=True)

    # ADR-415 D3. A leaked token must not be able to fill the table overnight,
    # and a per-IP rate limit does not stop a distributed flood on one token.
    daily_cap   = Column(Integer, nullable=False, server_default="500")

    created_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CollectedAddressProfile(Base):
    """One building profile submitted from the public collection page.

    Mirrors the observable half of `BuildingProfile` — what a person standing at
    a door can see. Deliberately absent: the verification lifecycle, GeoClient
    resolution, and the decaying troublesome score, all of which the system
    derives from many submissions rather than accepting from one.
    """
    __tablename__ = "collected_address_profiles"
    __table_args__ = (
        # The same address submitted twice for one campaign on one day is a
        # double-tap, not two observations. Scoped by collection date because a
        # building genuinely re-observed next week is new information.
        UniqueConstraint(
            "token_id", "collected_on", "address",
            name="uq_collected_profiles_token_day_address",
        ),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Resolved from the token, never from the request body (D2).
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_id    = Column(UUID(as_uuid=True),
                         ForeignKey("collection_tokens.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    # As typed. NOT normalised: GeoClient does that, and guessing at a canonical
    # form here would produce addresses matching nothing (ADR-277 D1).
    address     = Column(String(200), nullable=False)

    # ADR-417 D7 — the folded form of `address`, for duplicate detection only.
    #
    # Stored rather than computed per query so the campaign-wide check is an
    # index hit instead of a scan over every row folded on the fly. Never read
    # back as data and never exported: `address` is the record, this is a
    # lookup key. Indexed WITH token_id because every query filters on both.
    door_key    = Column(String(200), nullable=False, server_default="", index=True)

    building_type  = Column(String(30), nullable=False)
    workload_class = Column(String(20), nullable=False)

    # ── ADR-418 taxonomy ─────────────────────────────────────────────────────
    # See building_profile.py for the full reasoning. In short: category is
    # derived from type and written server-side; the security desk became a
    # flag because it is an attribute of the door, not a kind of door; and
    # workloads is a set because a doorman high-rise is genuinely both.
    building_category   = Column(String(20), nullable=False,
                                 server_default="unknown", index=True)
    has_security_desk   = Column(Boolean, nullable=False, server_default="false")
    workloads           = Column(JSONB, nullable=False, server_default="[]")
    # ADR-419. Free text behind the `other` workload tag. Kept OUT of
    # `raw_note`: the note is "anything else about this door" and this is an
    # answer to "which workload", so merging them would make it impossible to
    # tell later which half was which.
    workload_other      = Column(String(200), nullable=True)

    note        = Column(Text, nullable=True)

    opens_at    = Column(Time, nullable=True)
    closes_at   = Column(Time, nullable=True)
    break_start = Column(Time, nullable=True)
    break_end   = Column(Time, nullable=True)

    troublesome = Column(Boolean, nullable=False, server_default="false")

    # Free text, not a user id — the submitter has no account. Lets a later
    # analysis weight by observer without pretending to identify one.
    collected_by = Column(String(100), nullable=True)
    collected_on = Column(Date, nullable=False)

    submitted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Promotion review. Null = untouched; the rest is set by an authenticated
    # human, which is the whole point of the quarantine.
    review_status = Column(String(20), nullable=False, server_default="pending", index=True)
    reviewed_by   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    reviewed_at   = Column(DateTime(timezone=True), nullable=True)


class CollectedWalkerDay(Base):
    """One walker's logged day, submitted from the public route log (ADR-417 D3).

    A QUARANTINE TABLE, like `collected_address_profiles`. Nothing else reads
    it, nothing joins to it, and there is no promotion path into the routing
    model. That is deliberate and it is what makes the eventual PII strip a
    DELETE rather than a migration: `walker_name` holds real coworkers' names,
    stored verbatim because the whole point of the data is per-walker
    comparison against the sort output.

    The day's routes, totes, addresses, RTS and OVs live in one JSONB `payload`
    rather than five tables. Research data, one reader, a CSV as its output —
    normalising it would buy join performance nobody needs and cost a migration
    every time the field log grows a column.
    """
    __tablename__ = "collected_walker_days"
    __table_args__ = (
        # ADR-417 D5 — upsert key. One row per walker per date per campaign; a
        # resubmission REPLACES. The field connection drops mid-submit often
        # enough that a retry has to be safe, and the page already models one
        # row per walker per date locally.
        UniqueConstraint(
            "token_id", "collected_on", "walker_name",
            name="uq_collected_days_token_day_walker",
        ),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Resolved from the token, never from the request body (ADR-415 D2).
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_id    = Column(UUID(as_uuid=True),
                         ForeignKey("collection_tokens.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    # As typed. NOT resolved to employees.id: a FK would give referential
    # integrity and make the eventual strip a schema change touching live
    # relationships, where this is a DELETE.
    walker_name  = Column(String(100), nullable=False)
    collected_on = Column(Date, nullable=False, index=True)

    arrival_time   = Column(String(5), nullable=True)   # "HH:MM", station-local
    departure_time = Column(String(5), nullable=True)

    # Denormalised counts, written from the payload at submit time. They exist
    # so the super-admin listing can show "3 routes, 41 totes" without parsing
    # every payload — a read-time aggregate over JSONB would be the same work
    # repeated on every page load.
    route_count = Column(Integer, nullable=False, server_default="0")
    tote_count  = Column(Integer, nullable=False, server_default="0")
    rts_count   = Column(Integer, nullable=False, server_default="0")

    # The whole day, validated by WalkerDayIn before it lands here.
    payload = Column(JSONB, nullable=False, server_default="{}")

    submitted_at = Column(DateTime(timezone=True), nullable=False,
                          server_default=func.now())
    # Bumped on every overwrite, so a reader can tell a corrected day from a
    # first submission without diffing payloads.
    revision = Column(Integer, nullable=False, server_default="1")
