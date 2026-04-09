from sqlalchemy import Column, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class Truck(Base):
    """ORM model for a delivery truck.

    Attributes:
        id: Primary key UUID.
        name: Unique human-readable truck name.
        is_active: Whether the truck is currently in service and eligible for dispatch.
    """
    __tablename__ = "trucks"

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name      = Column(String(100),        nullable=False, unique=True, index=True)
    is_active = Column(Boolean,            nullable=False, default=True, index=True)
