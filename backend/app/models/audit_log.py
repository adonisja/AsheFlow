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

    company_id is nullable with NO foreign key constraint — intentional. Two reasons:
      1. super_admin actions cross company boundaries. When the platform owner acts
         on Company A's data, there is no honest single company_id to enforce via FK.
      2. System-generated actions (Celery jobs, auto-graduation) have no actor and
         no natural company_id to constrain.
    The column is still populated for all normal company-scoped actions so it is
    queryable. The service layer is responsible for passing the correct company_id —
    the DB will not catch mistakes here the way a FK would.
    """
    __tablename__ = "audit_logs"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=True,  index=True)
    actor_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type     = Column(String(80),  nullable=False, index=True)
    target_table    = Column(String(80),  nullable=False, index=True)
    target_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    before_snapshot = Column(JSONB, nullable=True)
    after_snapshot  = Column(JSONB, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
