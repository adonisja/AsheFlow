from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class EmployeeCreate(BaseModel):
    name: str
    discord_id: str
    role: str


class EmployeeUpdate(BaseModel):
    name:       Optional[str] = None
    discord_id: Optional[str] = None
    role:       Optional[str] = None


class EmployeeResponse(BaseModel):
    id: UUID
    name: str
    discord_id: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
