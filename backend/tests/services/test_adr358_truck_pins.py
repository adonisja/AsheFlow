"""ADR-358 — a person held to a truck on named weekdays.

The other pin axis. A crew pin (ADR-357) binds people to a DRIVER and follows
wherever that driver is drawn; a truck pin binds a person to a TRUCK on the days
they actually work it.

The most important test here is test_a_pinned_driver_does_not_create_two_drivers.
assign_drivers iterated EVERY truck and appended unconditionally, so seating any
driver beforehand produced two drivers on one truck — silently, with nothing
raised and no test failing.
"""
import datetime
import uuid as _uuid

from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship
from app.models.truck_pin import TruckPin
from app.services.seat_truck_pins import seat_truck_pins

COMPANY = _uuid.uuid4()
TUESDAY = datetime.date(2026, 9, 22)     # a Tuesday
WEDNESDAY = datetime.date(2026, 9, 23)


def _emp(db, role, name=None):
    e = Employee(
        id=_uuid.uuid4(), company_id=COMPANY, name=name or f"{role}-{_uuid.uuid4().hex[:5]}",
        role=role, is_active=True, account_status="active",
        reset_on_graduation=False, hr_system_id_adp=_uuid.uuid4(),
        hr_system_id_adp_verified=False,
    )
    db.add(e)
    return e


def _pin(db, emp, truck_id, day="Tuesday"):
    p = TruckPin(
        id=_uuid.uuid4(), company_id=COMPANY, employee_id=emp.id,
        truck_id=truck_id, day_of_week=day,
    )
    db.add(p)
    db.flush()
    return p


def test_a_pinned_employee_lands_on_their_truck_on_that_weekday(db):
    truck = _uuid.uuid4()
    walker = _emp(db, "walker")
    _pin(db, walker, truck, "Tuesday")

    crews = {str(truck): [], "other": []}
    pool = {"walkers": [walker]}

    warnings = seat_truck_pins(crews, pool, db, COMPANY, TUESDAY)

    assert [str(m["id"]) for m in crews[str(truck)]] == [str(walker.id)]
    assert crews["other"] == []
    assert pool["walkers"] == [], "a seated member left in the pool is assigned twice"
    assert warnings == []


def test_the_pin_is_inert_on_other_weekdays_and_silent(db):
    """D5 — a Tuesday pin is SUPPOSED to do nothing on Wednesday.

    Warning about it would train the reader to ignore pin warnings, which are
    the mechanism for the cases that do matter.
    """
    truck = _uuid.uuid4()
    walker = _emp(db, "walker")
    _pin(db, walker, truck, "Tuesday")

    crews = {str(truck): []}
    pool = {"walkers": [walker]}

    warnings = seat_truck_pins(crews, pool, db, COMPANY, WEDNESDAY)

    assert crews[str(truck)] == []
    assert pool["walkers"] == [walker]
    assert warnings == [], "an inert pin must not warn"


def test_a_pinned_driver_does_not_create_two_drivers(db):
    """D3 — THE latent bug this ADR found.

    assign_drivers iterated every truck and appended unconditionally, so a
    pre-seated driver produced a truck with two. Asserted end to end through the
    real driver pass, not on the filter expression.
    """
    from app.services.assign_drivers import assign_drivers

    truck_a, truck_b = str(_uuid.uuid4()), str(_uuid.uuid4())
    pinned = _emp(db, "driver")
    other = _emp(db, "driver")
    _pin(db, pinned, _uuid.UUID(truck_a), "Tuesday")
    db.flush()

    crews = {truck_a: [], truck_b: []}
    pool = {"drivers": [pinned, other]}

    seat_truck_pins(crews, pool, db, COMPANY, TUESDAY)
    assert [str(m["id"]) for m in crews[truck_a]] == [str(pinned.id)]

    assign_drivers(pool["drivers"], crews, {truck_a: 1.0, truck_b: 1.0}, db)

    for tid, crew in crews.items():
        drivers = [m for m in crew if m["role"] == "driver"]
        assert len(drivers) <= 1, f"truck {tid} ended with {len(drivers)} drivers"
    assert len([m for m in crews[truck_a] if m["role"] == "driver"]) == 1


def test_a_ban_outranks_the_truck_pin(db):
    """Authority order carried forward from ADR-357 D5: ban > pin > preference."""
    truck = _uuid.uuid4()
    driver = _emp(db, "driver")
    walker = _emp(db, "walker")
    _pin(db, walker, truck, "Tuesday")
    db.add(EmployeeRelationship(
        id=_uuid.uuid4(), company_id=COMPANY,
        employee_id=walker.id, target_employee_id=driver.id, relationship_type="ban",
    ))
    db.flush()

    crews = {str(truck): [{"id": driver.id, "role": "driver"}]}
    pool = {"walkers": [walker]}

    warnings = seat_truck_pins(crews, pool, db, COMPANY, TUESDAY)

    assert not any(str(m["id"]) == str(walker.id) for m in crews[str(truck)])
    assert pool["walkers"] == [walker]
    assert any(w["type"] == "truck_pin_ban_conflict" for w in warnings)


def test_a_taken_one_per_truck_slot_warns_rather_than_doubling(db):
    truck = _uuid.uuid4()
    manual, pinned = _emp(db, "captain"), _emp(db, "captain")
    _pin(db, pinned, truck, "Tuesday")

    crews = {str(truck): [{"id": manual.id, "role": "captain"}]}
    pool = {"captains": [pinned]}

    warnings = seat_truck_pins(crews, pool, db, COMPANY, TUESDAY)

    assert len([m for m in crews[str(truck)] if m["role"] == "captain"]) == 1
    assert any(w["type"] == "truck_pin_slot_taken" for w in warnings)


def test_a_truck_not_running_today_is_not_an_error(db):
    """A pin binds a person to a truck; it does not RESERVE the truck."""
    truck = _uuid.uuid4()
    walker = _emp(db, "walker")
    _pin(db, walker, truck, "Tuesday")

    crews = {"some-other-truck": []}
    pool = {"walkers": [walker]}

    warnings = seat_truck_pins(crews, pool, db, COMPANY, TUESDAY)

    assert pool["walkers"] == [walker]
    assert warnings == []


def test_seating_is_company_scoped(db):
    truck = _uuid.uuid4()
    walker = _emp(db, "walker")
    _pin(db, walker, truck, "Tuesday")

    crews = {str(truck): []}
    pool = {"walkers": [walker]}

    seat_truck_pins(crews, pool, db, _uuid.uuid4(), TUESDAY)

    assert crews[str(truck)] == [], "another tenant's dispatch must not read this pin"
    assert pool["walkers"] == [walker]
