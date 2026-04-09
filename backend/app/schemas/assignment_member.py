from pydantic import BaseModel
from uuid import UUID


class AssignmentMemberCreate(BaseModel):
    assignment_id: UUID
    employee_id: UUID
    role: str


class AssignmentMemberResponse(BaseModel):
    id: UUID
    assignment_id: UUID
    employee_id: UUID
    role: str

    model_config = {"from_attributes": True}
