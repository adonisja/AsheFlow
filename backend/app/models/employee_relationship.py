from sqlalchemy import Column, String, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class EmployeeRelationship(Base):
    """ORM model for a directional relationship between two employees.

    Supports two relationship types:
    - ``fav``: The employee prefers to work with the target — boosts co-assignment
      probability during dispatch weight calculation.
    - ``ban``: The employee refuses to work with the target — hard blocks
      co-assignment, with override rules for walker-vs-walker conflicts.

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
        CheckConstraint("relationship_type IN ('ban', 'fav')", name="ck_employee_relationships_type"),
    )

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id        = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    target_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type  = Column(String(10),         nullable=False)
