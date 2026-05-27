from pydantic import BaseModel, field_validator, EmailStr
from typing import Optional, Literal, List
from uuid import UUID
from datetime import datetime
import re

VALID_ROLES = ("driver", "walker", "trainer", "trainee", "dispatch", "management", "admin")
RoleStr = Literal["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"]

_SNOWFLAKE_RE = re.compile(r'^\d{17,20}$')


def _validate_discord_id(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    if not _SNOWFLAKE_RE.match(v):
        raise ValueError("discord_id must be a numeric Discord snowflake (17-20 digits)")
    return v


class EmployeeCreate(BaseModel):
    name: str
    email: EmailStr
    discord_id: Optional[str] = None
    role: RoleStr
    phone_number: Optional[str] = None

    @field_validator("discord_id", mode="before")
    @classmethod
    def validate_discord_id(cls, v):
        return _validate_discord_id(v)


class EmployeeUpdate(BaseModel):
    name:         Optional[str]     = None
    email:        Optional[EmailStr]     = None
    discord_id:   Optional[str]     = None
    role:         Optional[RoleStr] = None
    is_active:    Optional[bool]    = None
    phone_number: Optional[str]     = None

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
    cognito_sub: Optional[str] = None
    username: Optional[str] = None
    role: str
    is_active: bool
    phone_number: Optional[str] = None
    account_status: str = "active"
    invited_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BulkImportRow(BaseModel):
    """One row from a bulk import payload — same fields as EmployeeCreate."""
    name: str
    email: EmailStr
    discord_id: Optional[str] = None
    role: RoleStr
    phone_number: Optional[str] = None
    hr_system_id_adp: Optional[str] = None  # ADP associateOID; omitted for non-ADP imports

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

    Omits phone_number, email, and cognito_sub.
    """
    id: UUID
    name: str
    discord_id: Optional[str] = None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
