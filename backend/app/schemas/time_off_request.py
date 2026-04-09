from datetime import date
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class TimeOffRequestBase(BaseModel):
    employee_id: UUID
    date: date

class TimeOffRequestCreate(TimeOffRequestBase):
    pass

class TimeOffRequestUpdate(BaseModel):
    status: str

class TimeOffRequestResponse(TimeOffRequestBase):
    id: UUID
    status: str

    model_config = ConfigDict(from_attributes=True)
