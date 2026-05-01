from pydantic import BaseModel, field_validator
from typing import Optional, Literal, List
from uuid import UUID

VALID_ROLES = ("driver", "walker", "trainer", "trainee", "dispatch", "management", "admin")
RoleStr = Literal["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"]


class EmployeeCreate(BaseModel):
    name: str
    email: str
    discord_id: str
    role: RoleStr
    phone_number: Optional[str] = None


class EmployeeUpdate(BaseModel):
    name:         Optional[str]     = None
    email:        Optional[str]     = None
    discord_id:   Optional[str]     = None
    role:         Optional[RoleStr] = None
    is_active:    Optional[bool]    = None
    phone_number: Optional[str]     = None


class EmployeeResponse(BaseModel):
    """Full response — returned to management/admin/dispatch only."""
    id: UUID
    name: str
    email: Optional[str] = None
    discord_id: str
    cognito_sub: Optional[str] = None
    role: str
    is_active: bool
    phone_number: Optional[str] = None
    account_status: str = "active"

    model_config = {"from_attributes": True}


class BulkImportRow(BaseModel):
    """One row from a bulk import payload — same fields as EmployeeCreate."""
    name: str
    email: str
    discord_id: str
    role: RoleStr
    phone_number: Optional[str] = None


class BulkImportResult(BaseModel):
    """Per-row result returned from POST /employees/bulk."""
    row: int
    status: Literal["created", "skipped", "failed"]
    name: str
    email: str
    reason: Optional[str] = None


class EmployeePublicResponse(BaseModel):
    """Redacted response — returned to field staff (driver/walker/trainer/trainee).

    Omits phone_number, email, and cognito_sub.
    """
    id: UUID
    name: str
    discord_id: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
