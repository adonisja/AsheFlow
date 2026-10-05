"""REGISTRY drift guard for the employee-name redaction sweep (ADR-464).

`test_employee_redaction.py::test_registry_is_complete_and_valid` validates the
registry INWARD: every registered (fk, name) pair points at attributes that
really exist. That direction catches a rename or a deleted column.

It cannot catch the direction that actually leaks. A new `_by_name` column added
to a model and never registered passes that test untouched — the registry is
still internally valid, it is just incomplete, and the departed employee's name
sits in that column forever. ADR-221's own module docstring names the risk
("every new `_by_name` column MUST be added here, or a name escapes redaction")
with nothing enforcing it, and 15 columns had accumulated by the time anyone
looked.

So this walks the MODELS, not the registry, and requires every employee-name
column to be either registered or explicitly exempted below. A new one is a
failing test at the commit that adds it, not a privacy finding two years later.
"""
import app.models  # noqa: F401  — registers every mapper on Base.registry
from app.models.base import Base
from app.services.employee_redaction import REGISTRY


# Columns that look like an employee name but are not one, or are deliberately
# out of scope. Each entry needs a REASON — an unexplained exemption is how the
# allow-list becomes the leak it was written to prevent.
EXEMPT: dict[tuple[str, str], str] = {
    # --- Not a person ---
    ("btr_bags",         "amazon_route_name"): "Amazon's route label (e.g. CX7), not a person.",
    ("btr_routes",       "amazon_route_name"): "Amazon's route label, not a person.",
    ("route_sort_daily", "truck_name"):        "Vehicle name.",
    ("street_segments",  "street_name"):       "Street name from the NYC segment dataset.",
    ("trucks",           "name"):              "Vehicle name.",
    ("companies",        "name"):              "Tenant company name.",
    ("companies",        "amazon_dsp_name"):   "Tenant's Amazon-facing DSP name.",
    ("company_zones",    "name"):              "Operational zone label.",
    ("crew_pins",        "name"):              "Crew/pin label, not an employee identity.",

    # --- A person, but not a tenant employee (ADR-220) ---
    # BuildingProfileLibrary is the GLOBAL library: its actors are platform
    # super-admins, and the columns are deliberately FK-less UUIDs with no link
    # to any tenant's employees table. A tenant-scoped sweep must not touch them.
    ("building_profile_library", "created_by_name"):        "Platform super-admin, not a tenant employee.",
    ("building_profile_library", "updated_by_name"):        "Platform super-admin, not a tenant employee.",
    ("building_profile_library", "promoted_by_name"):       "Platform super-admin, not a tenant employee.",
    ("building_profile_library", "note_verified_by_name"):  "Platform super-admin, not a tenant employee.",
    ("building_profile_library", "hours_verified_by_name"): "Platform super-admin, not a tenant employee.",

    # --- The employee's own row ---
    # redact_employee_names() scrubs this directly in its self-scrub block
    # (name/email/phone/username), not via REGISTRY.
    ("employees", "name"): "Scrubbed by the self-scrub block in redact_employee_names().",
}

# Candidate FK partners for a `<stem>_name` column, in match order. A name column
# is only redactable if some column on the same table carries an FK to employees
# — that FK is what the sweep filters on.
def _fk_partners(stem: str) -> tuple[str, ...]:
    return (stem, f"{stem}_id", f"{stem}_employee_id", "employee_id")


def _employee_name_columns() -> list[tuple[str, str, str]]:
    """Every (table, name_column, fk_column) whose name column is paired with an
    FK to employees — i.e. everything the sweep is ABLE to redact."""
    found: list[tuple[str, str, str]] = []
    for mapper in Base.registry.mappers:
        table = getattr(mapper.class_, "__tablename__", None)
        if not table:
            continue
        columns = {c.key: c for c in mapper.columns}
        for key, col in columns.items():
            if not (key.endswith("_name") or key == "name"):
                continue
            stem = key[:-len("_name")] if key.endswith("_name") else key
            for candidate in _fk_partners(stem):
                partner = columns.get(candidate)
                if partner is None:
                    continue
                if any(fk.column.table.name == "employees" for fk in partner.foreign_keys):
                    found.append((table, key, candidate))
                    break
    return found


def test_every_employee_name_column_is_registered_or_exempt():
    """The outward check: no employee-name column escapes the sweep unnoticed.

    Fails on a column that has an employees FK partner but appears in neither
    REGISTRY nor EXEMPT. Fix by adding it to REGISTRY (the default — it is a
    real denormalized employee name), or to EXEMPT with a reason if it is not.
    """
    registered = {(model.__tablename__, name_attr) for model, _, name_attr in REGISTRY}

    unaccounted = [
        (table, name_col, fk_col)
        for table, name_col, fk_col in _employee_name_columns()
        if (table, name_col) not in registered and (table, name_col) not in EXEMPT
    ]

    assert not unaccounted, (
        "Employee-name column(s) not covered by the ADR-221 redaction sweep — a "
        "departed employee's name would persist here indefinitely:\n"
        + "\n".join(f"  {t}.{n}  (pair with fk: {f})" for t, n, f in sorted(unaccounted))
        + "\n\nAdd each to REGISTRY in app/services/employee_redaction.py as "
          "(Model, \"<fk>\", \"<name>\"), or to EXEMPT in this file with a reason."
    )


def test_exempt_entries_still_exist():
    """An EXEMPT entry for a column that no longer exists is stale — it hides
    nothing today but will silently cover a future column of the same name."""
    live = {
        (getattr(m.class_, "__tablename__", None), c.key)
        for m in Base.registry.mappers
        for c in m.columns
    }
    stale = [pair for pair in EXEMPT if pair not in live]
    assert not stale, (
        "EXEMPT lists column(s) that no longer exist — remove them:\n"
        + "\n".join(f"  {t}.{c}" for t, c in sorted(stale))
    )


def test_registry_entries_are_not_also_exempt():
    """A column in both lists is a contradiction: EXEMPT says 'never redact',
    REGISTRY says 'always redact'. REGISTRY wins at runtime, so the EXEMPT entry
    is a false reassurance to the next reader."""
    registered = {(model.__tablename__, name_attr) for model, _, name_attr in REGISTRY}
    both = registered & set(EXEMPT)
    assert not both, (
        "Column(s) in BOTH REGISTRY and EXEMPT — remove the EXEMPT entry:\n"
        + "\n".join(f"  {t}.{c}" for t, c in sorted(both))
    )
