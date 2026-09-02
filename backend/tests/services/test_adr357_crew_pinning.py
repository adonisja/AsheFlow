"""ADR-357 — a pinned crew is a constraint, not a preference.

Preferences top out at 88% for ONE candidate (ADR-356). Five people each winning
their own weighted draw is roughly 0.5%, so "this crew always rides together" is
unreachable by weighting no matter how the ladder is tuned. A pin is applied
before the draw.

These test seat_crew_pins directly rather than through run_dispatch: the whole
mechanism is "members are on the truck before their own pass runs", and that is
what is asserted.
"""
import uuid as _uuid

import pytest

from app.models.crew_pin import CrewPin, CrewPinMember
from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.services.seat_crew_pins import nullify_pins_for_ban, seat_crew_pins

COMPANY = _uuid.uuid4()


def _emp(db, role, name=None):
    e = Employee(
        id=_uuid.uuid4(), company_id=COMPANY, name=name or f"{role}-{_uuid.uuid4().hex[:5]}",
        role=role, is_active=True, account_status="active",
        reset_on_graduation=False, hr_system_id_adp=_uuid.uuid4(),
        hr_system_id_adp_verified=False,
    )
    db.add(e)
    return e


def _pin(db, driver, members, name="A Team", active=True):
    p = CrewPin(
        id=_uuid.uuid4(), company_id=COMPANY, name=name,
        driver_id=driver.id, is_active=active,
    )
    db.add(p)
    db.flush()
    for m in members:
        db.add(CrewPinMember(
            id=_uuid.uuid4(), company_id=COMPANY, pin_id=p.id, employee_id=m.id
        ))
    db.flush()
    return p


def _ban(db, a, b):
    db.add(EmployeeRelationship(
        id=_uuid.uuid4(), company_id=COMPANY,
        employee_id=a.id, target_employee_id=b.id, relationship_type="ban",
    ))
    db.flush()


def test_pinned_members_land_on_the_drivers_truck(db):
    """The property preferences cannot give: deterministic, not probabilistic."""
    driver = _emp(db, "driver")
    captain, walker = _emp(db, "captain"), _emp(db, "walker")
    _pin(db, driver, [captain, walker])

    crews = {"t1": [{"id": driver.id, "role": "driver"}], "t2": []}
    pool = {"captains": [captain], "walkers": [walker]}

    warnings = seat_crew_pins(crews, pool, db, COMPANY)

    seated = {str(m["id"]) for m in crews["t1"]}
    assert str(captain.id) in seated
    assert str(walker.id) in seated
    assert crews["t2"] == [], "nobody should land on the unrelated truck"
    assert warnings == []


def test_seated_members_are_removed_from_the_pool(db):
    """Dim 5 — otherwise their own pass places them a SECOND time."""
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    _pin(db, driver, [walker])

    crews = {"t1": [{"id": driver.id, "role": "driver"}]}
    pool = {"walkers": [walker]}

    seat_crew_pins(crews, pool, db, COMPANY)

    assert pool["walkers"] == [], (
        "a seated member left in the pool is assigned twice"
    )


def test_an_absent_driver_makes_the_pin_inactive_for_the_day(db):
    """D2 — members dispatch normally; no substitute anchor is chosen."""
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    _pin(db, driver, [walker])

    # Driver not dispatched: no truck carries them.
    crews = {"t1": [], "t2": []}
    pool = {"walkers": [walker]}

    warnings = seat_crew_pins(crews, pool, db, COMPANY)

    assert pool["walkers"] == [walker], "member must stay in the pool"
    assert all(c == [] for c in crews.values()), "nobody seated without an anchor"
    assert any(w["type"] == "crew_pin_driver_absent" for w in warnings)


def test_a_ban_outranks_the_pin(db):
    """D5 — ban > pin > preference.

    A ban is a working-relationship signal a person asserted about themselves; a
    pin is an operational convenience asserted about other people.
    """
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    _pin(db, driver, [walker])
    _ban(db, walker, driver)

    crews = {"t1": [{"id": driver.id, "role": "driver"}]}
    pool = {"walkers": [walker]}

    warnings = seat_crew_pins(crews, pool, db, COMPANY)

    seated = {str(m["id"]) for m in crews["t1"]}
    assert str(walker.id) not in seated, "a ban must beat the pin"
    assert pool["walkers"] == [walker]
    assert any(w["type"] == "crew_pin_ban_conflict" for w in warnings)


def test_an_inactive_pin_is_ignored(db):
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    _pin(db, driver, [walker], active=False)

    crews = {"t1": [{"id": driver.id, "role": "driver"}]}
    pool = {"walkers": [walker]}

    seat_crew_pins(crews, pool, db, COMPANY)
    assert pool["walkers"] == [walker]


def test_a_taken_one_per_truck_slot_is_not_double_filled(db):
    """A manual captain already on the truck must not be joined by a pinned one."""
    driver = _emp(db, "driver")
    manual_captain, pinned_captain = _emp(db, "captain"), _emp(db, "captain")
    _pin(db, driver, [pinned_captain])

    crews = {"t1": [
        {"id": driver.id, "role": "driver"},
        {"id": manual_captain.id, "role": "captain"},
    ]}
    pool = {"captains": [pinned_captain]}

    warnings = seat_crew_pins(crews, pool, db, COMPANY)

    captains = [m for m in crews["t1"] if m["role"] == "captain"]
    assert len(captains) == 1, "a truck must not end with two captains"
    assert any(w["type"] == "crew_pin_slot_taken" for w in warnings)


# ── D4: a ban between members nullifies the pin ──────────────────────────────

def test_a_ban_between_two_members_nullifies_the_pin(db):
    driver = _emp(db, "driver")
    a, b = _emp(db, "walker"), _emp(db, "walker")
    pin = _pin(db, driver, [a, b])

    nullified = nullify_pins_for_ban(db, COMPANY, a.id, b.id)

    assert [p.id for p in nullified] == [pin.id]
    assert pin.is_active is False
    assert pin.inactive_reason, "a dispatcher must not have to guess why"


def test_a_ban_involving_the_driver_also_nullifies(db):
    """The driver is the anchor and has no member row — both must be checked."""
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    pin = _pin(db, driver, [walker])

    nullify_pins_for_ban(db, COMPANY, walker.id, driver.id)
    assert pin.is_active is False


def test_a_ban_between_unrelated_people_leaves_the_pin_alone(db):
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    outsider_a, outsider_b = _emp(db, "walker"), _emp(db, "walker")
    pin = _pin(db, driver, [walker])

    assert nullify_pins_for_ban(db, COMPANY, outsider_a.id, outsider_b.id) == []
    assert pin.is_active is True


def test_nullification_is_company_scoped(db):
    """Dim 1 — this runs from a relationship endpoint; an unscoped query would
    reach another tenant's pins."""
    driver, walker = _emp(db, "driver"), _emp(db, "walker")
    pin = _pin(db, driver, [walker])

    other_company = _uuid.uuid4()
    assert nullify_pins_for_ban(db, other_company, walker.id, driver.id) == []
    assert pin.is_active is True, "another tenant's ban must not touch this pin"
