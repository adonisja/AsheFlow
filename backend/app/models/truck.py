from sqlalchemy import Column, String, Boolean, BigInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class Truck(Base):
    """ORM model for a delivery truck.

    Attributes:
        id: Primary key UUID.
        name: Unique truck name within a company (not globally).
        is_active: Whether the truck is currently in service and eligible for dispatch.
        discord_channel_id: Snowflake ID of the truck's Discord channel. Used by the
            bot to post finalized crew assignments and manage per-day channel access.
    """
    __tablename__ = "trucks"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id         = Column(UUID(as_uuid=True), nullable=False, index=True)
    name               = Column(String(100),        nullable=False, index=True)
    is_active          = Column(Boolean,            nullable=False, default=True, index=True)
    discord_channel_id = Column(BigInteger,         nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_trucks_company_name"),
    )
