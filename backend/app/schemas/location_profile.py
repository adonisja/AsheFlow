from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


BUILDING_TYPES = frozenset({
    "mailroom", "receptionist", "walkup", "elevator",
    "biz_front", "biz_freight", "biz_security", "biz_loading_dock",
})

WORKLOAD_CLASSES = frozenset({"bulk_drop", "high_touch", "standard", "high_wait"})

_BUILDING_TYPE_TO_WORKLOAD: dict[str, str] = {
    "mailroom":         "bulk_drop",
    "receptionist":     "bulk_drop",
    "walkup":           "high_touch",
    "elevator":         "standard",
    "biz_front":        "standard",
    "biz_freight":      "high_wait",
    "biz_security":     "high_touch",
    "biz_loading_dock": "bulk_drop",
}

BUILDING_TYPE_PROTOCOL: dict[str, str] = {
    "mailroom":         "Photo of packages in mail room.",
    "receptionist":     "Get the receptionist's name.",
    "walkup":           "Photo at front door.",
    "elevator":         "Photo at front door.",
    "biz_front":        "Photo at front door or get receptionist's name.",
    "biz_freight":      "Photo at front door or get receptionist's name.",
    "biz_security":     "Bring ID. Photo at front door.",
    "biz_loading_dock": "Photo at loading dock or get mail clerk's name.",
}


def derive_workload_class(building_type: str) -> str:
    return _BUILDING_TYPE_TO_WORKLOAD[building_type]


# ── create / submit ───────────────────────────────────────────────────────────

class LocationProfileCreate(BaseModel):
    block_key:     str = Field(..., max_length=60)
    building_type: str = Field(...)
    raw_notes:     Optional[str] = Field(None, max_length=2000)

    def validate_building_type(self) -> None:
        if self.building_type not in BUILDING_TYPES:
            raise ValueError(f"Invalid building_type: {self.building_type!r}")


# ── patch ─────────────────────────────────────────────────────────────────────

class LocationProfileVerify(BaseModel):
    """Captain/driver verifies the building_type. Increments agreement_count."""
    confirmed_building_type: str = Field(...)


class LocationProfileNotePatch(BaseModel):
    """Captain/management converts raw_notes to structured operational_note."""
    operational_note: str = Field(..., max_length=2000)


# ── response ──────────────────────────────────────────────────────────────────

class LocationProfileResponse(BaseModel):
    id:             UUID
    company_id:     UUID
    block_key:      str
    building_type:  str
    workload_class: str
    building_type_status:          str
    building_type_agreement_count: int
    nomination_status:  Optional[str] = None
    raw_notes:          Optional[str] = None
    operational_note:   Optional[str] = None
    note_verified:      bool
    note_verified_by:   Optional[UUID] = None
    note_verified_by_name: Optional[str] = None
    note_verified_at:   Optional[datetime] = None
    submitted_by:       Optional[UUID] = None
    submitted_by_name:  str
    submitted_at:       Optional[datetime] = None
    verified_by:        Optional[UUID] = None
    verified_by_name:   Optional[str] = None
    verified_at:        Optional[datetime] = None
    created_by:         Optional[UUID] = None
    created_by_name:    Optional[str] = None
    created_at:         datetime
    updated_at:         datetime
    # UI convenience — derived from building_type, not stored
    protocol_reminder:  str = ""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_with_protocol(cls, obj) -> "LocationProfileResponse":
        r = cls.model_validate(obj)
        r = r.model_copy(update={"protocol_reminder": BUILDING_TYPE_PROTOCOL.get(obj.building_type, "")})
        return r


# ── library response ──────────────────────────────────────────────────────────

class LocationProfileLibraryResponse(BaseModel):
    id:             UUID
    block_key:      str
    building_type:  str
    workload_class: str
    library_status: str
    agreement_source_count: int
    operational_note:  Optional[str] = None
    note_verified:     bool
    promoted_at:       Optional[datetime] = None
    last_conflict_at:  Optional[datetime] = None
    created_at:        datetime
    updated_at:        datetime
    protocol_reminder: str = ""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_with_protocol(cls, obj) -> "LocationProfileLibraryResponse":
        r = cls.model_validate(obj)
        r = r.model_copy(update={"protocol_reminder": BUILDING_TYPE_PROTOCOL.get(obj.building_type, "")})
        return r


# ── super admin patch (library) ───────────────────────────────────────────────

class LibraryStatusPatch(BaseModel):
    """Super admin resolves a conflict or deprecates a library record."""
    library_status: str = Field(...)   # "active" | "deprecated"
    operational_note: Optional[str] = Field(None, max_length=2000)


class NominationDecision(BaseModel):
    """Super admin approves or rejects a nomination."""
    decision: str = Field(...)   # "approved" | "rejected"
