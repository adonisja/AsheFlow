"""Request/response schemas for dispatch separations (ADR-361)."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeparationCreate(BaseModel):
    """Create a separation between two employees.

    No `Any` and no bare dict: this is attacker-controlled input at the trust
    boundary (CLAUDE.md Dimension 9). `reason` is the one free-text field and is
    capped.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    target_employee_id: UUID
    reason: str | None = Field(
        default=None,
        max_length=280,
        description=(
            "Why these two are kept apart. Stored in the audit log rather than "
            "on the row: EmployeeRelationship has no reason column, and adding "
            "one for a field only dispatch reads would put a free-text note "
            "about two people on a table three services join against. The audit "
            "log already answers who-decided-what and is access-controlled."
        ),
    )

    @model_validator(mode="after")
    def _not_self(self) -> "SeparationCreate":
        if self.employee_id == self.target_employee_id:
            raise ValueError("An employee cannot be separated from themselves.")
        return self


class SeparationResponse(BaseModel):
    """A separation, as dispatch sees it. Never returned to a field role."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    target_employee_id: UUID
    employee_name: str | None = None
    target_employee_name: str | None = None
