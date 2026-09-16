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
    # ADR-423. NULL means OPEN: a super-admin campaign belongs to no tenant,
    # which is the literal truth rather than a sentinel company standing in for
    # one. A company admin's campaign carries their id.
    #
    # This is what keeps the two kinds apart on read: a company admin filters by
    # their own id, which never matches NULL, so open data cannot appear in a
    # tenant view by construction rather than by remembering to exclude it.
    company_id  = Column(UUID(as_uuid=True), nullable=True, index=True)

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

    # ADR-423. A super admin has no Employee row — that is why the create
    # endpoint 403'd for them with "No employee record found for your account".
    # Already nullable, now genuinely used that way.
    created_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    # Who may submit, decided at creation and never inferred at submit time.
    #   "open"    — anyone with the link (super admin only)
    #   "company" — an authenticated employee of `company_id` (ADR-423 D2)
    scope       = Column(String(10), nullable=False, server_default="open", index=True)

    # WHAT may be submitted, decided at creation and never inferred (ADR-439).
    #   "addresses" — /submit, /check, /leaderboard
    #   "routes"    — /submit-day
    #
    # Separate from `scope` because the two axes vary independently: scope is
    # WHO may submit, this is WHAT they may submit. One combined enum would need
    # a new value every time either axis gained one.
    dataset     = Column(String(10), nullable=False, server_default="addresses", index=True)
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
    # Resolved from the token, never from the request body (ADR-415 D2).
    # NULL for an open campaign — see CollectionToken.company_id.
    company_id  = Column(UUID(as_uuid=True), nullable=True, index=True)
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

    # ADR-426. The device that submitted this row, so a collector can correct
    # their OWN entry after the door is locked.
    #
    # NOT an identity: a random id the page generates once and keeps in
    # localStorage. It says "the browser that sent this", nothing about who was
    # holding it, and clearing site data loses the ability to edit — which is
    # the honest consequence of not having accounts here.
    #
    # Indexed with door_key because the only query is "did THIS device already
    # submit THIS door under this campaign".
    device_id = Column(String(64), nullable=True, index=True)
    collected_on = Column(Date, nullable=False)

    submitted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Promotion review. Null = untouched; the rest is set by an authenticated
    # human, which is the whole point of the quarantine.
    review_status = Column(String(20), nullable=False, server_default="pending", index=True)
    reviewed_by   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    reviewed_at   = Column(DateTime(timezone=True), nullable=True)

