"""Oversized packages in workforce mode (ADR-400 A2/A4/A5).

An OV is ONE package that is too large to ride inside a tote. Workforce mode had
no representation for one at all: `BTROVZone` is written at BTR import and read
by nothing, so a truck with forty OVs sorted as though it had none — invisible on
the roster, unaddressable, and costing zero capacity.

WHY ITS OWN UNIT, NOT A PACKAGE INSIDE A TOTE (A4)
--------------------------------------------------
Full mode's manifest gives an OV the bag_id of the tote it ships beside, and
`route_sort._pair_ovs` reads that association. That is an artifact of Amazon's
file format, not a physical fact: only XS and S actually fit in a tote, while M,
L and XL ride on the cart next to it. Borrowing the id is also actively harmful
downstream — every reader then has to know to re-separate by `package_type`, and
any reader that forgets counts an OV as part of that tote's contents.

So an OV carries its own identity: `OV####`, minted per company per day.

WHY A TABLE RATHER THAN A ToteAddress ROW
------------------------------------------
Two reasons, both structural:
  - it needs `size` and `zone_label`, which a tote has no use for;
  - it must EXIST BEFORE IT HAS AN ADDRESS. A sheet-seeded OV is an expectation
    ("the sheet says four at B-27.2Y") that the captain later confirms.
    `ToteAddress` requires an address by construction, so it cannot hold one.
"""
import uuid

from sqlalchemy import (
    Column, String, Date, DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base

# A5b. Three-valued, not two. A mid-day OV is an ARRIVAL, not evidence the sheet
# was wrong: the operator receives freight from the station after the sheet has
# printed, and folding that into "captain added it" would make every normal
# milk-run look like a data-quality problem. "How much extra freight came in
# today" is a number the operation wants, and it is unrecoverable once mixed.
OV_SOURCES = ("sheet", "milk_run", "captain")

# Mirrors OV_HALF_SLOTS in schemas/walker_routes.py (XS 0, S 1, M 2, L 3, XL 4).
# Stored as the bare tier; the adapter turns it into `OV_{size}` so the genuine
# route_sort costs it through the path it already has (ADR-291 D5).
OV_SIZES = ("XS", "S", "M", "L", "XL")


class WorkforceOV(Base):
    """One oversized package on one truck on one day."""
    __tablename__ = "workforce_ovs"
    __table_args__ = (
        # A5d. THE RACE GUARD. Two captains on different trucks mint from one
        # daily company sequence, so `SELECT max(...) + 1` hands both the same
        # number. The constraint makes the loser's INSERT fail loudly and retry,
        # which is how this codebase already handles concurrent id assignment
        # (uq_routes_assignment_number, ADR-302 D3a).
        UniqueConstraint("company_id", "entry_date", "ov_id",
                         name="uq_workforce_ovs_company_date_id"),
        # The roster and the adapter both read by truck-day.
        Index("ix_workforce_ovs_truck_date", "company_id", "truck_id", "entry_date"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id   = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)

    # "OV0012". Unique per company per day and reset daily, so "OV12" means
    # today's twelfth — which is how a captain says it out loud. Deliberately NOT
    # fleetwide: a cross-tenant sequence would let one company's write rate shift
    # another's ids and would leak platform volume. Every neighbouring constraint
    # is company-scoped for the same reason.
    ov_id      = Column(String(20), nullable=False, index=True)

    # A5a. THE DRIVER'S FIELD, not the captain's. It answers a 06:00 question —
    # find B-27.2Y on a station shelf and pull the item — and is history by the
    # time the captain addresses it. Shown on the load roster, absent from
    # address entry. Null for anything that did not come from a sheet.
    zone_label = Column(String(30), nullable=True)

    # NULL until the captain says. Not defaulted: without a size the sort cannot
    # cost the route, and guessing "M" would silently understate or overstate
    # every unmeasured OV. The write path rejects an address entry that omits it.
    size       = Column(String(4), nullable=True)

    source     = Column(String(10), nullable=False, default="sheet")

    # NULL = expected but not yet in hand. A5c: an unconfirmed sheet OV is a
    # PRESENCE COUNT, never a loss claim, and never blocks the day close — the
    # same rule ADR-307 D1b applies to unchecked totes.
    confirmed_at   = Column(DateTime(timezone=True), nullable=True)
    confirmed_by   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
                            nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
