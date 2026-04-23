from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base
import uuid


class AuditLog(Base):
    """Immutable audit trail for privileged state-changing actions.

    One row per action. Never updated — only inserted.

    Attributes:
        id:              Primary key UUID.
        actor_id:        Employee UUID of who performed the action. NULL for system actions.
        action_type:     Dot-namespaced verb, e.g. 'pto.approved', 'incident.resolved'.
        target_table:    The DB table the action affected, e.g. 'time_off_requests'.
        target_id:       UUID of the affected row.
        before_snapshot: JSONB of the row state before the action (NULL for creates).
        after_snapshot:  JSONB of the row state after the action (NULL for deletes).
        created_at:      Timestamp of the action (server-set).
    """
    __tablename__ = "audit_logs"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type     = Column(String(80),  nullable=False, index=True)
    target_table    = Column(String(80),  nullable=False, index=True)
    target_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    before_snapshot = Column(JSONB, nullable=True)
    after_snapshot  = Column(JSONB, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
