import uuid
from sqlalchemy import Column, Integer, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class PackageManifest(Base):
    """Package load manifest for a truck on a given date.

    Submitted by dispatch or the driver at station load time. Records how many
    totes and OV (oversized/vehicle-loaded) packages were loaded onto the truck.
    One record per truck per date; updatable via PATCH if counts change.
    """
    __tablename__ = "package_manifests"
    __table_args__ = (
        UniqueConstraint("truck_id", "date", name="uq_package_manifests_truck_date"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    date            = Column(Date, nullable=False, index=True)
    tote_count      = Column(Integer, nullable=False, default=0)
    ov_count        = Column(Integer, nullable=False, default=0)   # oversized packages
    notes           = Column(Text, nullable=True)
    submitted_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name = Column(String(100), nullable=True)
    submitted_at      = Column(DateTime(timezone=True), server_default=func.now())
    # Driver acknowledgement — stamped when the driver confirms the manifest
    acknowledged_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    acknowledged_by_name = Column(String(100), nullable=True)
    acknowledged_at      = Column(DateTime(timezone=True), nullable=True)
