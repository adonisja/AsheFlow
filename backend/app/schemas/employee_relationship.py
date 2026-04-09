from pydantic import BaseModel
from uuid import UUID


class EmployeeRelationshipCreate(BaseModel):
    employee_id: UUID
    target_employee_id: UUID
    relationship_type: str


class EmployeeRelationshipResponse(BaseModel):
    id: UUID
    employee_id: UUID
    target_employee_id: UUID
    relationship_type: str

    model_config = {"from_attributes": True}
