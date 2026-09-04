"""A rule you can only create and delete is a rule you will get wrong twice (ADR-373).

Crew pins shipped with a PATCH that accepted `name` and `member_ids` from the
first commit, and a UI that only ever sent `{is_active}`. Truck pins could drop a
day but never gain one, and could never change truck at all. So every correction
was delete-and-recreate: a new id, a broken audit trail, and a window where the
person is pinned to nothing.

The retruck endpoint is keyed by EMPLOYEE rather than by pin id on purpose. Doing
it row by row can half-succeed and leave someone pinned to two different trucks
on different days -- which the model permits and nobody intended.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.models.crew_pin import CrewPin, CrewPinMember
from app.models.truck_pin import TruckPin
from app.routers import crew_pins as CP
from app.routers import truck_pins as TP
from app.schemas.crew_pin import CrewPinUpdate
from app.schemas.truck_pin import TruckPinCreate, TruckPinRetruck
from tests.conftest import SEED_COMPANY_ID, make_employee, make_truck


def _pin(db, emp, truck, day="Tuesday"):
    p = TruckPin(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=emp.id,
        truck_id=truck.id, day_of_week=day,
    )
    db.add(p)
    db.commit()
    return p


def _crew(db, driver, members, name="Alpha"):
    pin = CrewPin(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, name=name,
        driver_id=driver.id, is_active=True,
    )
    db.add(pin)
    db.flush()
    for m in members:
        db.add(CrewPinMember(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID,
            pin_id=pin.id, employee_id=m.id,
        ))
    db.commit()
    return pin


class TestCrewPinEditing:
    def test_renaming_keeps_the_id_members_and_active_state(self, db):
        """Delete-and-recreate was the only way to rename; it loses all three."""
        driver = make_employee(db, "driver", "Rename Driver")
        walker = make_employee(db, "walker", "Rename Walker")
        pin = _crew(db, driver, [walker], name="Old Name")
        original_id, original_active = pin.id, pin.is_active

        out = CP.update_crew_pin(
            pin_id=pin.id, body=CrewPinUpdate(name="New Name"),
            db=db, caller=driver, _=None,
        )

        assert out.id == original_id, "a rename must not mint a new pin"
        assert out.name == "New Name"
        assert out.is_active == original_active, "a rename must not disturb active state"
        assert {m.employee_id for m in out.members} == {walker.id}, (
            "a rename must not touch the roster"
        )

    def test_changing_members_adds_and_removes_only_what_changed(self, db):
        driver = make_employee(db, "driver", "Member Driver")
        keep = make_employee(db, "walker", "Keep")
        drop = make_employee(db, "walker", "Drop")
        add = make_employee(db, "walker", "Add")
        pin = _crew(db, driver, [keep, drop])

        out = CP.update_crew_pin(
            pin_id=pin.id,
            body=CrewPinUpdate(member_ids=[keep.id, add.id]),
            db=db, caller=driver, _=None,
        )

        assert out.id == pin.id, "the pin id must survive a roster edit"
        assert {m.employee_id for m in out.members} == {keep.id, add.id}
        rows = db.query(CrewPinMember).filter(
            CrewPinMember.pin_id == pin.id
        ).all()
        assert len(rows) == 2, f"expected exactly 2 member rows, got {len(rows)}"


class TestTruckPinRetruck:
    def test_moving_an_employee_rewrites_every_day_row(self, db):
        """Keyed by employee: all days move, or the person is on two trucks."""
        emp = make_employee(db, "walker", "Mover")
        old = make_truck(db, "Truck Old")
        new = make_truck(db, "Truck New")
        _pin(db, emp, old, "Tuesday")
        _pin(db, emp, old, "Thursday")

        out = TP.retruck_employee_pins(
            employee_id=emp.id, body=TruckPinRetruck(truck_id=new.id),
            db=db, caller=emp, _=None,
        )

        assert len(out) == 2, "both days must come back"
        assert {p.truck_id for p in out} == {new.id}
        left = db.query(TruckPin).filter(
            TruckPin.employee_id == emp.id, TruckPin.truck_id == old.id
        ).count()
        assert left == 0, f"{left} day-row(s) stayed on the old truck"

    def test_moving_writes_an_audit_row(self, db):
        from app.models.audit_log import AuditLog

        emp = make_employee(db, "walker", "Audited")
        old, new = make_truck(db, "Aud Old"), make_truck(db, "Aud New")
        _pin(db, emp, old, "Monday")

        before = db.query(AuditLog).filter(
            AuditLog.action_type == "truck_pin.retrucked"
        ).count()
        TP.retruck_employee_pins(
            employee_id=emp.id, body=TruckPinRetruck(truck_id=new.id),
            db=db, caller=emp, _=None,
        )
        after = db.query(AuditLog).filter(
            AuditLog.action_type == "truck_pin.retrucked"
        ).count()

        assert after == before + 1, "a retruck must leave an audit row"

    def test_another_tenants_truck_is_not_a_valid_destination(self, db):
        """Dimension 1.

        A random UUID does NOT test this: it is absent from every company, so it
        404s whether or not the query is scoped. The destination has to be a
        truck that really exists, just not here -- otherwise dropping
        `Truck.company_id == caller.company_id` leaves the test green.
        """
        from app.models.truck import Truck as TruckModel

        emp = make_employee(db, "walker", "Tenant Scoped")
        home = make_truck(db, "Home Truck")
        _pin(db, emp, home, "Monday")

        other_company = uuid.uuid4()
        foreign = TruckModel(
            id=uuid.uuid4(), company_id=other_company,
            name="Other Tenant Truck", is_active=True,
        )
        db.add(foreign)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            TP.retruck_employee_pins(
                employee_id=emp.id,
                body=TruckPinRetruck(truck_id=foreign.id),
                db=db, caller=emp, _=None,
            )
        assert exc.value.status_code == 404
        assert "Truck not found" in exc.value.detail

        still_home = db.query(TruckPin).filter(
            TruckPin.employee_id == emp.id).all()
        assert {p.truck_id for p in still_home} == {home.id}, (
            "a refused retruck must leave every day-row where it was"
        )

    def test_an_employee_with_no_pins_is_a_404_not_a_silent_success(self, db):
        emp = make_employee(db, "walker", "Unpinned")
        truck = make_truck(db, "Some Truck")

        with pytest.raises(HTTPException) as exc:
            TP.retruck_employee_pins(
                employee_id=emp.id, body=TruckPinRetruck(truck_id=truck.id),
                db=db, caller=emp, _=None,
            )
        assert exc.value.status_code == 404
        assert "no truck pins" in exc.value.detail

    def test_someone_on_a_crew_pin_cannot_be_retrucked(self, db):
        """ADR-358 D2 re-checked here: an invariant guarded at one door only."""
        driver = make_employee(db, "driver", "Clash Driver")
        walker = make_employee(db, "walker", "Clash Walker")
        old, new = make_truck(db, "Clash Old"), make_truck(db, "Clash New")
        _pin(db, walker, old, "Monday")
        _crew(db, driver, [walker], name="Clash Crew")

        with pytest.raises(HTTPException) as exc:
            TP.retruck_employee_pins(
                employee_id=walker.id, body=TruckPinRetruck(truck_id=new.id),
                db=db, caller=driver, _=None,
            )
        assert exc.value.status_code == 409
        assert "Clash Crew" in exc.value.detail, (
            "the message must name the crew, or the dispatcher cannot act on it"
        )


class TestAddingADay:
    def test_adding_a_day_creates_one_row_and_leaves_the_rest(self, db):
        """ADR-373 D2 -- POST already does this; no new endpoint was needed."""
        emp = make_employee(db, "walker", "Day Adder")
        truck = make_truck(db, "Day Truck")
        first = _pin(db, emp, truck, "Tuesday")

        TP.create_truck_pins(
            body=TruckPinCreate(employee_id=emp.id, truck_id=truck.id, days=["Friday"]),
            db=db, caller=emp, _=None,
        )

        days = {p.day_of_week for p in db.query(TruckPin).filter(
            TruckPin.employee_id == emp.id).all()}
        assert days == {"Tuesday", "Friday"}
        assert db.query(TruckPin).filter(TruckPin.id == first.id).first() is not None, (
            "adding a day must not disturb the day already held"
        )

    def test_adding_a_day_already_held_is_refused_by_name(self, db):
        emp = make_employee(db, "walker", "Dup Day")
        truck = make_truck(db, "Dup Truck")
        _pin(db, emp, truck, "Tuesday")

        with pytest.raises(HTTPException) as exc:
            TP.create_truck_pins(
                body=TruckPinCreate(
                    employee_id=emp.id, truck_id=truck.id, days=["Tuesday"],
                ),
                db=db, caller=emp, _=None,
            )
        assert exc.value.status_code == 409
        assert "Tuesday" in exc.value.detail, (
            "the 409 must name the day, or the dispatcher cannot tell which one clashed"
        )
