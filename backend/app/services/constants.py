# ---------------------------------------------------------------------------
# Role constants — single source of truth for all employee role strings.
# Import these instead of scattering bare string literals across routers.
# ---------------------------------------------------------------------------

# Field-operational roles that appear on daily dispatch assignments.
# NOTE: nothing imports this today — `employees.py:304` defines its own shadowing
# copy, which is the one actually in force. Widened for correctness; fixing the
# shadow is a separate cleanup.
FIELD_ROLES: tuple[str, ...] = ("captain", "driver", "trainer", "trainee", "walker")

# Back-office roles that manage or administer the platform
MANAGEMENT_ROLES: tuple[str, ...] = ("management", "admin")

# Privileged staff who can see/manage other employees' data.
#
# ADR-256 D12 adds field_supervisor. This is a WIDER grant than "oversight reads":
# `deps.py::_PRIVILEGED_ROLES` derives from this tuple and is the ownership-bypass
# in `assert_can_access`, so a field supervisor can now read another employee's
# records — within their own tenant, which that helper still enforces separately.
# That is intended for a road-facing supervisor, but it is a consequence of editing
# this line, not of any per-endpoint decision. Adding a role here grants it
# everywhere `assert_can_access` is called.
OVERSIGHT_ROLES: tuple[str, ...] = ("management", "admin", "dispatch", "field_supervisor")

# Roles that receive dispatch assignments (appear in assigned_crews).
# NOTE: no importers — see FIELD_ROLES above. The list actually enforced at the
# trust boundary is the Literal in `schemas/dispatch.py`, which must be widened
# with captain separately; this tuple alone grants nothing.
ASSIGNABLE_ROLES: tuple[str, ...] = (
    "captain", "driver", "trainer", "trainee", "walker", "driver_trainee",
)

# Shortcuts for individual roles
ROLE_DRIVER    = "driver"
ROLE_TRAINER   = "trainer"
ROLE_TRAINEE   = "trainee"
ROLE_WALKER    = "walker"
ROLE_DISPATCH  = "dispatch"
ROLE_MANAGEMENT = "management"
ROLE_ADMIN     = "admin"
ROLE_CAPTAIN   = "captain"
ROLE_FIELD_SUPERVISOR = "field_supervisor"
ROLE_DRIVER_TRAINEE = "driver_trainee"   # ADR-264

# ---------------------------------------------------------------------------
# Authority sets (ADR-256)
#
# Named for the SCOPE THEY GRANT, not the group they serve — ADR-242's lesson.
# `_allow_captain` was a list of five roles of which "captain" was not even one;
# the name invited exactly the misreading that let `_allow_mgmt` hand dispatch the
# ability to read and delete individual scorecards.
# ---------------------------------------------------------------------------

# Who may lead a truck's route work: build/assign/reassign routes, own RTS and
# reattempts, resolve misroutes. ADR-256 D5 removes `trainer` — under the new
# hierarchy a trainer sits BELOW a captain and raises needs rather than deciding.
# `driver` stays: the captain organises routes WITH the driver.
ROUTE_LEAD_ROLES: tuple[str, ...] = (
    "captain", "driver", "dispatch", "field_supervisor", "management", "admin",
)

# Truck-scoped elevation: roles whose reads are narrowed to their OWN truck.
# Distinct from ROUTE_LEAD_ROLES, which includes station-side roles that see every
# truck. Adding a role here without a `_caller_truck_id` scope is a cross-truck leak.
TRUCK_SCOPED_ROLES: tuple[str, ...] = ("driver", "captain")

# Station-side reconciliation: resolving missing/damaged packages and handoff
# discrepancies. ADR-256 D12 keeps field_supervisor OUT — they oversee the road,
# and ADR-016 settled that an oversight role does not thereby acquire dispatch's
# execution authority.
STATION_RESOLVE_ROLES: tuple[str, ...] = ("dispatch", "management", "admin")

# ---------------------------------------------------------------------------

