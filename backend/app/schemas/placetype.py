"""Request shapes for choosing a PlaceType door (ADR-584 D4), shared by every
path that can hold an address for a tenant to pick: Sort, tote entry, intake."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PickedDoor(BaseModel):
    """A door the tenant picked from the nearby or same-street list."""
    model_config = ConfigDict(extra="forbid")
    borough: Literal["1", "2", "3", "4", "5"]
    address: str = Field(..., min_length=3, max_length=200)


class MapPin(BaseModel):
    """A point the tenant chose. New York only."""
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(..., ge=40.47, le=40.93)
    lng: float = Field(..., ge=-74.27, le=-73.68)
