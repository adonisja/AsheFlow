"""A stolen-package report: one theft, two versions (ADR-512).

The DSP's own report form, field for field. There are usually two reports of one
theft: the DA files one, and the truck's driver or captain reviews it, may edit any
field, and signs a copy attributed to them. Both versions are kept, so dispatch and
management can see where they disagree (computed at read time, never stored).

`Incident` remains the event: its notification, severity and resolution. This
table holds the category's 14 fields, which do not belong on the generic table.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, Time, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.mutable import MutableList

from app.models.base import Base


class ReportVersion(StrEnum):
    DA = "da"
    #: Signed by the truck's driver OR captain (owner's amendment, 2026-10-14),
    #: so it is named for the act, not the role.
    REVIEWER = "reviewer"


class StolenPackageReport(Base):
    __tablename__ = "stolen_package_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    version = Column(String(10), nullable=False)

    #: Who wrote this version: the DA for `da`, the signer for `reviewer`.
    #: CASCADE matches Incident.reporter_id: a hard employee delete is erasure.
    author_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    #: The DA the report is about. An FK, never a copied name (ADR-499).
    da_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
                            nullable=True)

    incident_date = Column(Date, nullable=False)
    incident_time = Column(Time, nullable=True)
    #: A CUSTOMER delivery address: Personal Information (ADR-493). Registered
    #: for erasure; cleared 60 days after `incident_date` (ADR-512 D5).
    incident_address = Column(Text, nullable=True)
    #: The DSP's own truck staging point at the incident time, snapshotted:
    #: not a customer address (same exemption as trucks.initial_anchor_address).
    anchor_point_address = Column(String(255), nullable=True)

    lmet_called = Column(Boolean, nullable=False, default=False)
    lmet_case_number = Column(String(64), nullable=True)
    bike_locks_used = Column(Boolean, nullable=False, default=True)
    cart_cover_used = Column(Boolean, nullable=False, default=True)
    totes_stolen = Column(Integer, nullable=False, default=0)
    cart_stolen = Column(Boolean, nullable=False, default=False)
    packages_stolen = Column(Integer, nullable=False, default=0)
    #: Package ids: Personal Information (ADR-493). Registered for erasure (a
    #: placeholder per element, so the count survives); cleared at 60 days.
    #: MutableList so an in-place edit is not silently discarded (ADR-247).
    tbas = Column(MutableList.as_mutable(ARRAY(String(40))), nullable=False, default=list)
    summary = Column(Text, nullable=False)

    #: Reviewer only. Visible to dispatch/management/admin; never in the
    #: copied report and never in a field-staff response (ADR-512 D5, D6).
    reviewer_comments = Column(Text, nullable=True)
    #: One-way stamp on the reviewer version (409 on a second sign).
    signed_at = Column(DateTime(timezone=True), nullable=True)
    #: When the 60-day retention cleared address and TBAs, so "empty because
    #: cleared" is distinguishable from "never entered".
    pi_cleared_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                        onupdate=func.now())

    __table_args__ = (
        Index("uq_stolen_report_version", "incident_id", "version", unique=True),
        CheckConstraint("version IN ('da', 'reviewer')", name="ck_stolen_report_version"),
        CheckConstraint("totes_stolen >= 0 AND packages_stolen >= 0", name="ck_stolen_report_counts"),
    )
