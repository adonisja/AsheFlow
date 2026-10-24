"""A door that keeps coming back: the tenant's decaying RTS signal (ADR-584 D6).

Was a score on `BuildingProfile`, which forced `record_rts_incident` to create a
stub profile ("system:rts") for every unseen address. A troublesome door is the
TENANT's observation keyed by door identity (borough, canonical address,
ADR-582), and needs no profile to exist. The scoring rules are ADR-218's.
"""
import uuid

from sqlalchemy import Column, DateTime, Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class TroublesomeDoor(Base):
    __tablename__ = "troublesome_doors"
    __table_args__ = (
        UniqueConstraint("company_id", "borough", "address", name="uq_troublesome_doors_door"),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    # NYC borough code "1".."5". NULL only for scores copied from BuildingProfile
    # before ADR-584, whose borough couldn't be resolved in a migration.
    borough          = Column(String(1), nullable=True)
    address          = Column(String(200), nullable=False)
    score            = Column(Float, nullable=False, server_default="0", default=0.0)
    last_incident_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at      = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
