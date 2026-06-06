from datetime import date, datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class DriverSurveyCreate(BaseModel):
    date: date


class DriverSurveyResponseCreate(BaseModel):
    routes_organized:      bool
    anchor_point_location: bool
    supplies_ready:        bool
    driver_support:        bool
    notes:                 Optional[str] = None


# ── Response shapes ──────────────────────────────────────────────────────────

class DriverSurveyResponseItem(BaseModel):
    id:                    UUID
    respondent_id:         UUID
    respondent_name:       str
    respondent_email:      Optional[str]
    respondent_role:       str
    truck_name:            Optional[str]
    driver_name:           Optional[str]
    routes_organized:      bool
    anchor_point_location: bool
    supplies_ready:        bool
    driver_support:        bool
    notes:                 Optional[str]
    submitted_at:          datetime

    model_config = ConfigDict(from_attributes=True)


class SurveyStats(BaseModel):
    expected_count:        int
    response_count:        int
    routes_organized_pct:  float   # 0-100
    anchor_location_pct:   float
    supplies_ready_pct:    float
    driver_support_pct:    float


class DriverSurveyDetail(BaseModel):
    id:         UUID
    date:       date
    created_at: datetime
    stats:      SurveyStats
    responses:  List[DriverSurveyResponseItem]

    model_config = ConfigDict(from_attributes=True)


class DriverSurveyListItem(BaseModel):
    id:             UUID
    date:           date
    created_at:     datetime
    expected_count: int
    response_count: int

    model_config = ConfigDict(from_attributes=True)


class MyResponseStatus(BaseModel):
    responded: bool
    response:  Optional[DriverSurveyResponseItem] = None
