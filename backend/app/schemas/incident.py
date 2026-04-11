from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import date, time, datetime
from typing import Optional

VALID_CATEGORIES = {
    "vehicle", "injury", "stolen_packages", "customer_complaint",
    "route_issue", "crew_conduct", "safety_hazard", "other",
}
VALID_SEVERITIES = {"info", "warning", "critical"}

# Default severity per category — frontend uses this, backend validates minimum
CATEGORY_DEFAULT_SEVERITY = {
    "injury": "critical",
    "stolen_packages": "warning",
    "vehicle": "warning",
    "crew_conduct": "warning",
    "safety_hazard": "warning",
    "customer_complaint": "info",
    "route_issue": "info",
    "other": "info",
}


class IncidentCreate(BaseModel):
    reporter_id: UUID
    date: date
    category: str
    severity: str
    description: str
    photo_url: Optional[str] = None

    # Stolen packages
    incident_time: Optional[time] = None
    packages_tba: Optional[int] = None
    incident_location: Optional[str] = None
    witness_name: Optional[str] = None

    # Injury
    body_part_affected: Optional[str] = None
    medical_attention_required: Optional[bool] = None


class IncidentResponse(BaseModel):
    id: UUID
    reporter_id: UUID
    truck_id: Optional[UUID] = None
    date: date
    category: str
    severity: str
    description: str
    photo_url: Optional[str] = None

    incident_time: Optional[time] = None
    packages_tba: Optional[int] = None
    incident_location: Optional[str] = None
    witness_name: Optional[str] = None

    body_part_affected: Optional[str] = None
    medical_attention_required: Optional[bool] = None

    driver_id: Optional[UUID] = None

    resolved: bool
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentListItem(BaseModel):
    """Slim response used in management list views — omits photo payload."""
    id: UUID
    reporter_id: UUID
    reporter_name: Optional[str] = None
    truck_id: Optional[UUID] = None
    truck_name: Optional[str] = None
    driver_id: Optional[UUID] = None
    driver_name: Optional[str] = None
    date: date
    category: str
    severity: str
    description: str
    resolved: bool
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
