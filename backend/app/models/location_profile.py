from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.models.base import Base

class LocationProfile(Base):
    __tablename__ = "location_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "block_key", "building_type", name="uq_location_profiles_company_block_type"),
    )
    
    # 1. Identity — what this record describes
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    block_key = Column(String(60), nullable=False)
    building_type = Column(String(30), nullable=False)
    workload_class = Column(String(20), nullable=False)

    # 2. Building type lifecycle — the locking/verification flow
    building_type_status = Column(String(20), server_default="pending")
    building_type_agreement_count = Column(Integer, server_default="0")

    # 3. Notes lifecycle — the separate note verification flow
    raw_notes = Column(Text, nullable=True)
    operational_note = Column(Text, nullable=True)
    note_verified = Column(Boolean, server_default="false")
    note_verified_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"))
    note_verified_by_name = Column(String)
    note_verified_at = Column(DateTime(timezone=True))

    # 4. Submission audit — who first reported this
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name = Column(String(100), nullable=False)
    submitted_at = Column(DateTime(timezone=True))

    # 5. Verification audit — who verified the building type
    verified_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    verified_by_name = Column(String(100))
    verified_at = Column(DateTime(timezone=True))

    # 6. Record audit — standard created_by + timestamps
    created_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_by_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)