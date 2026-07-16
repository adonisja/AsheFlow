from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class ScorecardMetricIn(BaseModel):
    key: str = Field(..., max_length=50)
    label: str = Field(..., max_length=100)
    value: str = Field(..., max_length=50)
    unit: Optional[str] = Field(None, max_length=20)
    tier: Optional[str] = Field(None, max_length=30)
    flag: Optional[Literal["excellent", "needs_focus"]] = None
    sort_order: int = 0


class ScorecardMetricOut(ScorecardMetricIn):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class ScorecardCreate(BaseModel):
    """Manager creates/updates a scorecard for a week (structured entry — this is
    what the upload+confirm step writes). scope='company' → employee_id omitted."""
    week: str = Field(..., max_length=10, description='ISO week, e.g. "2026-W28"')
    scope: Literal["individual", "company"] = "individual"
    employee_id: Optional[UUID] = None
    overall_standing: Optional[str] = Field(None, max_length=30)
    source_file_url: Optional[str] = None
    metrics: List[ScorecardMetricIn] = []


class ScorecardDraftOut(BaseModel):
    """Parsed-but-unsaved scorecard (ADR-204 Phase C). The manager reviews/edits
    this in the entry form, then saves via POST /scorecards."""
    week: Optional[str] = None
    overall_standing: Optional[str] = None
    metrics: List[ScorecardMetricIn] = []


class ScorecardOut(BaseModel):
    id: UUID
    week: str
    scope: str
    employee_id: Optional[UUID] = None
    employee_name: Optional[str] = None
    overall_standing: Optional[str] = None
    source_file_url: Optional[str] = None
    created_at: datetime
    metrics: List[ScorecardMetricOut] = []
    model_config = ConfigDict(from_attributes=True)
