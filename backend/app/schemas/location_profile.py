from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


WORKLOAD_CLASSES = frozenset({"bulk_drop", "high_touch", "standard", "high_wait"})

BUILDING_TYPES = frozenset({
    "mailroom", "receptionist", "doorman", "walkup", "elevator",
    "biz_front", "biz_freight", "biz_security", "biz_loading_dock",
})

_BUILDING_TYPE_TO_WORKLOAD: dict[str, str] = {
    "mailroom":          "bulk_drop",
    "receptionist":      "bulk_drop",
    "doorman":           "bulk_drop",
    "walkup":            "high_touch",
    "elevator":          "standard",
    "biz_front":         "standard",
    "biz_freight":       "high_wait",
    "biz_security":      "high_touch",
    "biz_loading_dock":  "bulk_drop",
}

BUILDING_TYPE_PROTOCOL: dict[str, str] = {
    "mailroom":          "Photo of packages in mail room.",
    "receptionist":      "Get the receptionist's name.",
    "doorman":           "Hand to doorman. Get name if required.",
    "walkup":            "Photo at front door.",
    "elevator":          "Photo at front door.",
    "biz_front":         "Photo at front door or get receptionist's name.",
    "biz_freight":       "Photo at front door or get receptionist's name.",
    "biz_security":      "Bring ID. Photo at front door.",
    "biz_loading_dock":  "Photo at loading dock or get mail clerk's name.",
}


def derive_workload_class(building_type: str) -> str:
    return _BUILDING_TYPE_TO_WORKLOAD[building_type]


# ── BuildingProfile schemas ───────────────────────────────────────────────────

class BuildingProfileCreate(BaseModel):
    """Walker submits a new building profile for a stop they just completed.

    normalised_address is passed directly from the frontend stop state — it is
    the GeoClient-normalised address already in memory from the enriched manifest.
    block_key may be passed from stop context to skip server-side derivation; if
    omitted, the router derives it from normalised_address via derive_block_key.
    """
    normalised_address: str           = Field(..., max_length=200)
    block_key:          Optional[str] = Field(None, max_length=60)
    building_type:      str           = Field(...)
    raw_note:           Optional[str] = Field(None, max_length=2000)

    def validate_building_type(self) -> None:
        if self.building_type not in BUILDING_TYPES:
            raise ValueError(f"Invalid building_type: {self.building_type!r}")


class BuildingProfileVerify(BaseModel):
    """Captain/dispatch verifies the building_type. Increments agreement_count."""
    confirmed_building_type: str = Field(...)
    # Captain may also override workload_class independently of building_type
    workload_class_override: Optional[str] = Field(None)


class BuildingProfileNotePatch(BaseModel):
    """Captain converts raw_note to structured operational_note."""
    operational_note: str = Field(..., max_length=2000)


class BuildingProfileAnchorPatch(BaseModel):
    """Dispatch sets or clears the initial anchor point for a building profile."""
    lat:  Optional[float] = Field(None, ge=-90,  le=90)
    lng:  Optional[float] = Field(None, ge=-180, le=180)
    note: Optional[str]   = Field(None, max_length=200)


class BuildingProfileResponse(BaseModel):
    id:                  UUID
    company_id:          UUID
    normalised_address:  str
    block_key:           str
    building_type:       str
    workload_class:      str
    raw_note:            Optional[str] = None
    operational_note:    Optional[str] = None
    note_verified:       bool
    building_type_status:           str
    building_type_agreement_count:  int
    nomination_status:   Optional[str] = None
    submitted_by:        Optional[UUID] = None
    submitted_by_name:   str
    submitted_at:        Optional[datetime] = None
    verified_by:         Optional[UUID] = None
    verified_by_name:    Optional[str] = None
    verified_at:         Optional[datetime] = None
    # Initial anchor point — set by dispatch; feeds AP workflow + sort pipeline
    initial_anchor_lat:          Optional[float]    = None
    initial_anchor_lng:          Optional[float]    = None
    initial_anchor_note:         Optional[str]      = None
    initial_anchor_set_by:       Optional[UUID]     = None
    initial_anchor_set_by_name:  Optional[str]      = None
    initial_anchor_set_at:       Optional[datetime] = None
    created_at:          datetime
    updated_at:          datetime
    # Derived — not stored
    protocol_reminder:   str = ""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_with_protocol(cls, obj) -> "BuildingProfileResponse":
        r = cls.model_validate(obj)
        r = r.model_copy(update={"protocol_reminder": BUILDING_TYPE_PROTOCOL.get(obj.building_type, "")})
        return r


# ── BuildingProfileLibrary schemas ────────────────────────────────────────────

class BuildingProfileLibraryResponse(BaseModel):
    id:                  UUID
    normalised_address:  str
    block_key:           str
    building_type:       str
    workload_class:      str
    operational_note:    Optional[str] = None
    note_verified:       bool
    library_status:      str
    agreement_source_count: int
    last_conflict_at:    Optional[datetime] = None
    promoted_at:         Optional[datetime] = None
    created_at:          datetime
    updated_at:          datetime
    protocol_reminder:   str = ""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_with_protocol(cls, obj) -> "BuildingProfileLibraryResponse":
        r = cls.model_validate(obj)
        r = r.model_copy(update={"protocol_reminder": BUILDING_TYPE_PROTOCOL.get(obj.building_type, "")})
        return r


class BuildingProfileLibraryStatusPatch(BaseModel):
    """Super admin resolves a conflict or deprecates a library record."""
    library_status:   str = Field(...)   # "active" | "deprecated"
    operational_note: Optional[str] = Field(None, max_length=2000)
