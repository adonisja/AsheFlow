"""ADR-493 D3 — one row per erasure, holding a keyed hash of what was erased.

Never the value itself: a ledger that stored the address would re-persist the
thing the erasure removed. HMAC-SHA256 with `settings.pi_erasure_hmac_key`, so
the ledger cannot be reversed by hashing a list of candidate addresses without
the key. `replay_ledger` re-applies these after a backup restore (ADR-349's
30-day Object Lock means a restored copy predates recent erasures).
"""
import uuid
from sqlalchemy import CheckConstraint, Column, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class PiErasureLedger(Base):
    __tablename__ = "pi_erasure_ledger"
    __table_args__ = (
        Index("ix_pi_erasure_ledger_company_erased_at", "company_id", "erased_at"),
        CheckConstraint("kind IN ('address', 'tba')", name="ck_pi_erasure_ledger_kind"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL for a platform erasure of tenant-less rows (open campaigns, Library).
    company_id = Column(UUID(as_uuid=True), nullable=True)
    kind       = Column(String(10), nullable=False)          # "address" | "tba"
    value_hash = Column(String(64), nullable=False, index=True)
    # Employee id for a tenant erasure; platform staff identity is a Cognito sub,
    # so it is stored as text rather than a FK.
    erased_by  = Column(String(64), nullable=True)
    erased_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
