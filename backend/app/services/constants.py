# ---------------------------------------------------------------------------
# Role constants — single source of truth for all employee role strings.
# Import these instead of scattering bare string literals across routers.
# ---------------------------------------------------------------------------

# Field-operational roles that appear on daily dispatch assignments
FIELD_ROLES: tuple[str, ...] = ("driver", "trainer", "trainee", "walker")

# Back-office roles that manage or administer the platform
MANAGEMENT_ROLES: tuple[str, ...] = ("management", "admin")

# Privileged staff who can see/manage other employees' data
OVERSIGHT_ROLES: tuple[str, ...] = ("management", "admin", "dispatch")

# Roles that receive dispatch assignments (appear in assigned_crews)
ASSIGNABLE_ROLES: tuple[str, ...] = ("driver", "trainer", "trainee", "walker")

# Shortcuts for individual roles
ROLE_DRIVER    = "driver"
ROLE_TRAINER   = "trainer"
ROLE_TRAINEE   = "trainee"
ROLE_WALKER    = "walker"
ROLE_DISPATCH  = "dispatch"
ROLE_MANAGEMENT = "management"
ROLE_ADMIN     = "admin"

# ---------------------------------------------------------------------------

