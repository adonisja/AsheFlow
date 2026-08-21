"""Pydantic models for ADP Workforce Now API responses."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class WorkerID(BaseModel):
    """ADP workerID object."""

    id_value: str = Field(alias="idValue")

    class Config:
        populate_by_name = True


class Person(BaseModel):
    """Person object with name and contact info."""

    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    email: Optional[str] = None
    phone: Optional[str] = None
    birth_date: Optional[date] = Field(None, alias="birthDate")

    class Config:
        populate_by_name = True


class StatusCode(BaseModel):
    """Status code object (e.g., Active, Terminated)."""

    code_value: str = Field(alias="codeValue")

    class Config:
        populate_by_name = True


class AssignmentStatus(BaseModel):
    """Assignment status object."""

    status_code: StatusCode = Field(alias="statusCode")

    class Config:
        populate_by_name = True


class WorkAssignment(BaseModel):
    """Work assignment (job) for a worker."""

    item_id: str = Field(alias="itemID")
    assignment_status: AssignmentStatus = Field(alias="assignmentStatus")
    position_id: Optional[str] = Field(None, alias="positionID")
    hire_date: Optional[date] = Field(None, alias="hireDate")
    termination_date: Optional[date] = Field(None, alias="terminationDate")

    class Config:
        populate_by_name = True


class Worker(BaseModel):
    """ADP Worker (Employee) object."""

    associate_oid: str = Field(alias="associateOID")
    worker_id: WorkerID = Field(alias="workerId")
    person: Person
    work_assignments: List[WorkAssignment] = Field(alias="workAssignments")

    @property
    def primary_assignment_status(self) -> str:
        """Get status from first/primary work assignment."""
        if self.work_assignments:
            return self.work_assignments[0].assignment_status.status_code.code_value
        return "Unknown"

    @property
    def is_terminated(self) -> bool:
        """Check if worker is terminated."""
        return self.primary_assignment_status == "Terminated"

    @property
    def hire_date(self) -> Optional[date]:
        """Get hire date from primary work assignment."""
        if self.work_assignments:
            return self.work_assignments[0].hire_date
        return None

    class Config:
        populate_by_name = True


class WorkerListResponse(BaseModel):
    """Response from GET /hr/v2/workers endpoint."""

    workers: List[Worker]
    paging: Optional[dict] = None

    class Config:
        populate_by_name = True


class PayPeriod(BaseModel):
    """ADP Pay Period object."""

    pay_period_id: str = Field(alias="payPeriodID")
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    payroll_group_id: Optional[str] = Field(None, alias="payrollGroupID")
    status: Optional[str] = None

    class Config:
        populate_by_name = True


class PayPeriodListResponse(BaseModel):
    """Response from GET /payroll/v2/payroll-groups/{id}/pay-periods endpoint."""

    pay_periods: List[PayPeriod] = Field(alias="payPeriods")
    paging: Optional[dict] = None

    class Config:
        populate_by_name = True


class BreakEntry(BaseModel):
    """Break entry within a timecard."""

    break_out: Optional[str] = Field(None, alias="breakOut")
    break_in: Optional[str] = Field(None, alias="breakIn")

    class Config:
        populate_by_name = True


class TimeCard(BaseModel):
    """ADP Timecard (Time Entry) object."""

    entry_id: str = Field(alias="entryID")
    date: date
    punch_in: Optional[str] = Field(None, alias="punchIn")
    punch_out: Optional[str] = Field(None, alias="punchOut")
    breaks: List[BreakEntry] = Field(default_factory=list)
    total_hours: Optional[float] = Field(None, alias="totalHours")
    status: Optional[str] = None
    notes: Optional[str] = None
    validation_errors: List[dict] = Field(default_factory=list, alias="validationErrors")

    class Config:
        populate_by_name = True


class TimeCardListResponse(BaseModel):
    """Response from GET /time/v2/workers/{aoid}/time-cards endpoint."""

    time_cards: List[TimeCard] = Field(alias="timeCards")
    paging: Optional[dict] = None

    class Config:
        populate_by_name = True
