from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class AssignmentMemberCreate(BaseModel):
    assignment_id: UUID
    employee_id: UUID
    role: str


class AssignmentMemberResponse(BaseModel):
    id: UUID
    company_id: UUID
    assignment_id: UUID
    employee_id: UUID
    role: str
    paired_trainer_id: Optional[UUID] = None

    model_config = {"from_attributes": True}
