from sqlalchemy import Column, String, Boolean, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class TruckAssignment(Base):
    """ORM model for a daily truck assignment record.

    One record is created per truck per dispatch run.  All crew members
    for that truck on that day are stored as related ``AssignmentMember`` rows.

    Constraints & Safety:
    - ``truck_id`` and ``date`` combination MUST be unique (preventing double dispatch).
    - Cascading deletes are enforced; deleting the truck deletes its history.

    Attributes:
        id: Primary key UUID.
        truck_id: Foreign key to the assigned truck.
        date: The date this assignment is for.
        status: Lifecycle status — one of ``planned``, ``active``, or ``completed``.
    """
    __tablename__ = "truck_assignments"
    __table_args__ = (
        UniqueConstraint("truck_id", "date", name="uq_truck_assignment_date"),
        CheckConstraint("status IN ('planned', 'active', 'completed')", name="ck_truck_assignments_status"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id            = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    date                = Column(Date,               nullable=False, index=True)
    status              = Column(String(50),         nullable=False, default="planned")
    sort_initiated_by       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    sort_committed_at       = Column(DateTime(timezone=True), nullable=True)
    paired_arrival_confirmed = Column(Boolean, nullable=False, default=False)
    # ADR-274 D17: the physical bay this truck occupies for the day, set by
    # dispatch on the assignment page and DM'd to the crew at publish.
    #
    # On the ASSIGNMENT, not on Truck: a bay can differ day to day, so a column
    # on Truck would silently rewrite history every time it changed. It is also
    # not on DockAssignment (per-driver) — a dock is a place a TRUCK sits, and
    # every driver crewed on it collects from the same bay. DockAssignment stays
    # the per-driver read the home cards use, written from this at publish.
    #
    # Nullable: a truck-day with no bay set yet is normal, and the value is
    # prefilled from the truck's previous assignment for dispatch to confirm.
    dock_zone           = Column(String(50), nullable=True)
    # ADR-368 D3: why dispatch created this assignment on its own, when it did.
    # "truck_pin" means a hub had someone pinned to it for this weekday, so the
    # run created the assignment rather than skipping the pin.
    #
    # On the ASSIGNMENT rather than derived at read time: answering "was this
    # auto-created?" from "does a matching pin exist?" flips to false the moment
    # the pin is edited or deleted, rewriting history. ADR-274 named that trap.
    #
    # Nullable, and null for every hand-created assignment -- the board renders a
    # distinct treatment only when it is set, because an assignment nobody asked
    # for is worse than none if it appears silently.
    auto_created_reason = Column(String(40), nullable=True)

    # ADR-290: the warehouse zone where THIS TRUCK'S TOTES are staged ("BTR31").
    #
    # A DIFFERENT PLACE from dock_zone above. dock_zone is where the driver
    # collects the vehicle; this is where the load is picked. An earlier draft of
    # ADR-290 proposed splitting dock_zone on the theory it conflated the two —
    # it does not (see that ADR's context correction), so this is purely
    # additive and the six existing dock_zone readers are untouched.
    #
    # Denormalised from BTRSheet.btr_loading_zone at import so the dispatch board
    # and the driver's home card can show it without joining the sheet tables.
    btr_loading_zone    = Column(String(50), nullable=True)

    # ADR-295 — the Discord message id of the crew embed posted to this truck's
    # channel, so a later crew change can EDIT that message instead of leaving
    # a stale roster standing and posting a correction beside it.
    #
    # BigInteger, not String: a Discord snowflake is a 64-bit int, and
    # trucks.discord_channel_id already stores one this way.
    #
    # Nullable, and it must stay nullable: every row predating this column has
    # no embed, a truck whose channel post failed has none, and D4 CLEARS this
    # back to NULL when a fetch finds the message deleted — that reset is what
    # stops the next crew change retrying a dead fetch. A non-null default
    # would make "no embed" unrepresentable.
    crew_embed_message_id = Column(BigInteger, nullable=True)
