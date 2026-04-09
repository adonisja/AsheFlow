from pydantic import BaseModel
from uuid import UUID


class EmployeeOffDayCreate(BaseModel):
    employee_id: UUID
    day_of_week: str

class EmployeeOffDayUpdate(BaseModel):
    day_of_week: str

class EmployeeOffDayUpdate(BaseModel):
    day_of_week: str


class EmployeeOffDayResponse(BaseModel):
    id: UUID
    employee_id: UUID
    day_of_week: str
    status: str

    model_config = {"from_attributes": True}
