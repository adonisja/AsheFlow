from pydantic import BaseModel, field_validator, EmailStr, Field
from typing import Optional, Literal, List
from uuid import UUID
from datetime import datetime
import re

# Mirrors app/models/employee.py VALID_ROLES — the two copies must stay in sync.
# ADR-256: captain, field_supervisor. ADR-264: driver_trainee (enum value only).
VALID_ROLES = (
    "driver", "walker", "trainer", "trainee", "dispatch", "management", "admin",
    "captain", "field_supervisor", "driver_trainee",
)
RoleStr = Literal[
    "driver", "walker", "trainer", "trainee", "dispatch", "management", "admin",
    "captain", "field_supervisor", "driver_trainee",
]

_SNOWFLAKE_RE = re.compile(r'^\d{17,20}$')


def _validate_discord_id(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    if not _SNOWFLAKE_RE.match(v):
        raise ValueError("discord_id must be a numeric Discord snowflake (17-20 digits)")
    return v


class EmployeeCreate(BaseModel):
    name: str = Field(..., max_length=100)
    email: EmailStr
    discord_id: Optional[str] = None
    role: RoleStr
    phone_number: Optional[str] = Field(None, max_length=20)

    @field_validator("discord_id", mode="before")
    @classmethod
    def validate_discord_id(cls, v):
        return _validate_discord_id(v)


class EmployeeUpdate(BaseModel):
    name:         Optional[str]      = Field(None, max_length=100)
    email:        Optional[EmailStr] = None
    discord_id:   Optional[str]      = None
    role:         Optional[RoleStr]  = None
    is_active:    Optional[bool]     = None
    phone_number: Optional[str]      = Field(None, max_length=20)

    @field_validator("discord_id", mode="before")
    @classmethod
    def validate_discord_id(cls, v):
        return _validate_discord_id(v)


class EmployeeResponse(BaseModel):
    """Full response — returned to management/admin/dispatch only."""
    id: UUID
    name: str
    email: Optional[EmailStr] = None
    discord_id: Optional[str] = None
    username: Optional[str] = None
    role: str
    is_active: bool
    phone_number: Optional[str] = None
    account_status: str = "active"
    invited_at: Optional[datetime] = None
    injury_status: Optional[str] = None
    injury_status_since: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InjuryStatusPatch(BaseModel):
    """Body for PATCH /employees/{id}/injury-status."""
    injury_status: Optional[Literal["injured", "disabled"]] = None


class BulkImportRow(BaseModel):
    """One row from a bulk import payload — same fields as EmployeeCreate."""
    name: str = Field(..., max_length=100)
    email: EmailStr
    discord_id: Optional[str] = None
    role: RoleStr
    phone_number: Optional[str] = Field(None, max_length=20)
    hr_system_id_adp: Optional[str] = Field(None, max_length=50)  # ADP associateOID; omitted for non-ADP imports

    @field_validator("discord_id", mode="before")
    @classmethod
    def validate_discord_id(cls, v):
        return _validate_discord_id(v)


class BulkImportResult(BaseModel):
    """Per-row result returned from POST /employees/bulk."""
    row: int
    status: Literal["created", "skipped", "failed"]
    name: str
    email: EmailStr
    reason: Optional[str] = None


class EmployeePublicResponse(BaseModel):
    """Redacted response — returned to field staff (driver/walker/trainer/trainee).

    Omits phone_number, email, cognito_sub, and discord_id.
    """
    id: UUID
    name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
