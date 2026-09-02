from sqlalchemy import Column, String, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class EmployeeRelationship(Base):
    """ORM model for a directional relationship between two employees.

    Supports three relationship types:
    - ``fav``: The employee prefers to work with the target — boosts co-assignment
      probability during dispatch weight calculation.
    - ``ban``: The employee refuses to work with the target — hard blocks
      co-assignment, with override rules for walker-vs-walker conflicts.
    - ``sep``: Dispatch has separated two people (ADR-361). Same hard block as a
      ban at every enforcement site, but it is a DISPATCHER's decision rather
      than either employee's. The pair occupies ``employee_id`` and
      ``target_employee_id`` exactly as a ban does — the record's whole content
      is which two people — and the author is recorded in the audit log.

      Because the pair sits in the same columns as a ban, a ``sep`` is NOT
      invisible for free: every employee-facing read must exclude it explicitly
      (the per-employee GET, and the DELETE that would let someone remove one).
      It does not consume either employee's 2-ban cap, and the walker-vs-walker
      ban override does not release it.

    Constraints & Safety:
    - ``employee_id``, ``target_employee_id``, and ``relationship_type`` combination
      MUST be unique (Employee A can only ban Employee B exactly once).
    - Cascading deletes are enforced; deleting either employee obliterates the relationship.

    Attributes:
        id: Primary key UUID.
        employee_id: The employee who owns the relationship.
        target_employee_id: The employee the relationship points to.
        relationship_type: Either ``fav`` or ``ban``.
    """
    __tablename__ = "employee_relationships"
    __table_args__ = (
        UniqueConstraint("employee_id", "target_employee_id", "relationship_type", name="uq_emp_relationship"),
        CheckConstraint("relationship_type IN ('ban', 'fav', 'sep')", name="ck_employee_relationships_type"),
    )

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    target_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type  = Column(String(10),         nullable=False)
