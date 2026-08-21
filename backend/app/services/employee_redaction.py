"""Employee-name redaction across denormalized _by_name copies (ADR-221).

Employee names are denormalized into ~40 `_by_name` columns so "who did this"
survives after the person leaves. Policy (ADR-217): retain the name while active
+ 6 months after departure, then redact. Hard delete redacts immediately.

Each `_by_name` is paired with a `_by` FK to employees. The sweep redacts
`name_attr` → REDACTED_NAME wherever `fk_attr == employee_id`. CRITICAL: the FK
uses ondelete=SET NULL, so the match only works WHILE the FK still points at the
employee — run the sweep BEFORE deleting the row (hard delete) or on the
still-linked tombstone (6-month deactivation).

REGISTRY is the single source of truth — every new `_by_name` column MUST be
added here, or a name escapes redaction (same explicit-list discipline as the
private-repo sync TESTS list). BuildingProfileLibrary is intentionally EXCLUDED:
its actor is the platform super-admin, not a tenant employee (ADR-220).
"""
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.anchor_point import AnchorPoint
from app.models.assignment_change_request import AssignmentChangeRequest
from app.models.building_profile import BuildingProfile
from app.models.delivery_stop import DeliveryStop
from app.models.dock_assignment import DockAssignment
from app.models.incident import Incident
from app.models.package_manifest import PackageManifest
from app.models.rts import RTSPackage, MissingPackage, RouteHandoff, ReattemptAssignment
from app.models.rts_clearance import RTSReport
from app.models.schedule_change_request import ScheduleChangeRequest
from app.models.tote_ops import ToteTransfer, ToteLoadCheck, PackageRemoval
from app.models.truck_zone import TruckZone
from app.models.walker_route import Route, MisroutedPackageFlag

REDACTED_NAME = "[former employee]"

# (Model, fk_attr, name_attr). Only pairs with a real employee FK — free-text
# name fields with no FK (e.g. Incident.witness_name/driver_name) can't be
# reliably tied to an employee_id and are handled separately (see module note).
REGISTRY: list[tuple[type, str, str]] = [
    (AnchorPoint,             "confirmed_by",          "confirmed_by_name"),
    (AssignmentChangeRequest, "reviewed_by",           "reviewed_by_name"),
    (BuildingProfile,         "note_verified_by",      "note_verified_by_name"),
    (BuildingProfile,         "verified_by",           "verified_by_name"),
    (BuildingProfile,         "hours_verified_by",     "hours_verified_by_name"),
    (BuildingProfile,         "initial_anchor_set_by", "initial_anchor_set_by_name"),
    (BuildingProfile,         "created_by",            "created_by_name"),
    (DeliveryStop,            "walker_id",             "walker_name"),
    (DockAssignment,          "assigned_by",           "assigned_by_name"),
    (Incident,                "resolved_by",           "resolved_by_name"),
    (Incident,                "driver_id",             "driver_name"),
    (Incident,                "witness_id",            "witness_name"),   # ADR-221: witness FK added
    (PackageManifest,         "submitted_by",          "submitted_by_name"),
    (PackageManifest,         "acknowledged_by",       "acknowledged_by_name"),
    (RTSPackage,              "walker_id",             "walker_name"),
    (MissingPackage,          "walker_id",             "walker_name"),
    (MissingPackage,          "resolved_by",           "resolved_by_name"),
    (RouteHandoff,            "walker_id",             "walker_name"),
    (RouteHandoff,            "driver_id",             "driver_name"),
    (RouteHandoff,            "discrepancy_resolved_by", "discrepancy_resolved_by_name"),
    (ReattemptAssignment,     "assigned_by",           "assigned_by_name"),
    (ReattemptAssignment,     "original_walker_id",    "original_walker_name"),
    (ReattemptAssignment,     "assigned_to",           "assigned_to_name"),
    (RTSReport,               "reviewed_by",           "reviewed_by_name"),
    (ScheduleChangeRequest,   "reviewed_by",           "reviewed_by_name"),
    (ToteTransfer,            "resolved_by",           "resolved_by_name"),
    (ToteLoadCheck,           "checked_by",            "checked_by_name"),
    (PackageRemoval,          "removed_by",            "removed_by_name"),
    (PackageRemoval,          "handed_over_by",        "handed_over_by_name"),
    (PackageRemoval,          "received_by",           "received_by_name"),
    (TruckZone,               "created_by",            "created_by_name"),
    (MisroutedPackageFlag,    "resolved_by",           "resolved_by_name"),
]
REGISTRY = [r for r in REGISTRY if r is not None]


def redact_employee_names(db: Session, employee_id: UUID) -> dict[str, int]:
    """Redact all denormalized name copies for one employee → REDACTED_NAME,
    matched via the paired FK. Also nulls the employee row's own PII.
    Caller owns the transaction (commit outside). Returns per-model counts.

    Must run while the FK still resolves (before hard delete; on the tombstone
    for the 6-month path).
    """
    counts: dict[str, int] = {}
    for model, fk_attr, name_attr in REGISTRY:
        fk_col = getattr(model, fk_attr, None)
        if fk_col is None or not hasattr(model, name_attr):
            continue
        n = (
            db.query(model)
            .filter(fk_col == employee_id, getattr(model, name_attr).isnot(None))
            .update({getattr(model, name_attr): REDACTED_NAME}, synchronize_session=False)
        )
        if n:
            counts[f"{model.__tablename__}.{name_attr}"] = n

    # Scrub the employee row's own PII (keep id/company_id/role/deactivated_at for
    # FLSA headcount + FK integrity).
    from app.models.employee import Employee
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if emp is not None:
        emp.name = REDACTED_NAME
        emp.email = None
        emp.phone_number = None
        emp.username = None
        counts["employees.self"] = 1
    return counts
