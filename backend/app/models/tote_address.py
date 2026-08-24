"""Captain-entered delivery addresses for a tote (ADR-291).

In workforce mode there is no manifest, so a captain supplies the geography: one
or more delivery addresses per tote, minimum one. The sort then runs UNCHANGED —
these become PackageInput records and `run_sort` never learns where they came
from (ADR-291 D5).

WHY A ROW PER ADDRESS RATHER THAN AN ARRAY ON THE BAG
`_Tote.dominant_block_key` already resolves a tote's block by MAJORITY VOTE
across its packages. Three captain addresses vote exactly the way forty package
addresses do, so one row per address means the existing vote works untouched
(ADR-291 D2). An array column would need its own tallying logic beside a vote
that already exists.

Storing every entered address, not just the winning block, is what makes the
vote reproducible: a re-sort sees the same inputs, and a second address can be
added mid-morning without re-entering the first (D3).

RETENTION
These are customer delivery addresses. They inherit ADR-219's 48-hour nulling
like every other address in the system — `normalised_address` is erased while
`block_key` survives, because a block key cannot reconstruct a house number.
Being captain-typed rather than Amazon-supplied changes nothing about that.
"""
import uuid

from sqlalchemy import (
    Column, String, Float, Date, DateTime, ForeignKey, Integer, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class ToteAddress(Base):
    """One delivery address a captain entered against one tote."""
    __tablename__ = "tote_addresses"
    __table_args__ = (
        # The same address typed twice for one tote on one day is a
        # double-submit, not two stops. Scoped by date because the same bag id
        # recurs on later days carrying different work.
        UniqueConstraint(
            "company_id", "truck_id", "entry_date", "bag_id", "raw_address",
            name="uq_tote_addresses_bag_address",
        ),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id   = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)

    # The physical tote. Matches BTRBag.bag_id when a BTR sheet was imported,
    # but deliberately NOT a foreign key: a captain must be able to enter an
    # address for a tote that is on the truck even when the sheet was never
    # imported, or was imported wrong. The sheet is a convenience, not a gate.
    bag_id     = Column(String(50), nullable=False, index=True)

    # What the captain typed, kept verbatim so a bad geocode can be re-run
    # against the original rather than a normalised guess.
    #
    # ADR-219: nulled 48h after entry_date, exactly like every other delivery
    # address. block_key survives the purge and is what the sort actually uses.
    raw_address        = Column(String(300), nullable=True)
    normalised_address = Column(String(200), nullable=True)

    # Derived by derive_block_key from the address. THE ROUTING KEY — both modes
    # route on block_key (ADR-291 D1, upholding ADR-238 D4a). Null when the
    # address could not be parsed; the entry is still stored so the captain can
    # see and fix it rather than having it silently vanish.
    block_key  = Column(String(100), nullable=True, index=True)

    lat        = Column(Float, nullable=True)
    lng        = Column(Float, nullable=True)

    # From GeoClient, feeding route_sort's cross-street adjacency graph. Null in
    # workforce mode when geocoding failed — the sort degrades to block_key
    # adjacency, which is the graph it uses anyway.
    first_cross_street  = Column(String(120), nullable=True)
    second_cross_street = Column(String(120), nullable=True)

    # Ties break by first-entered so a re-sort is stable (ADR-291 D2). Assigned
    # server-side, never client-supplied.
    entry_sequence = Column(Integer, nullable=False, default=0)

    entered_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
                             nullable=True)
    entered_by_name = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
