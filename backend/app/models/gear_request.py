import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class GearOrder(Base):
    """A gear request submission — one cart per employee per submission.

    Status lives on GearOrderItem, not here. The order is the grouping
    envelope; managers act on individual items within it.
    """
    __tablename__ = "gear_orders"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GearOrderItem(Base):
    """A single line item within a GearOrder.

    item:   shirt_long | shirt_short | pants | shorts | jacket | vest | cap | gloves
    size:   XS/S/M/L/XL/XXL/3XL for most; S/M/L for gloves; NULL for cap
    season: summer | winter  — set at submission time from company local date
    status: pending | approved | denied | fulfilled
    """
    __tablename__ = "gear_order_items"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id    = Column(UUID(as_uuid=True), ForeignKey("gear_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)

    item   = Column(String(20), nullable=False)
    size   = Column(String(5), nullable=True)
    season = Column(String(10), nullable=False)  # "summer" | "winter"
    status = Column(String(15), nullable=False, default="pending")

    approved_by  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    approved_at  = Column(DateTime(timezone=True), nullable=True)
    fulfilled_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)
    notes        = Column(Text, nullable=True)  # denial reason or fulfillment note

    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
