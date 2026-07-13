"""Tests for the Crew Status page endpoint (ADR-197 Phase B).

crew_status is public (no proprietary imports). These exercise the branch logic
that the endpoint adds on top of the availability derivation: role scoping,
trip_count pass-through, pairing maps, and the orphaned-trainee flag.
"""
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.routers.crew_status import get_crew_status


_CID = uuid.uuid4()
_DATE = date(2026, 7, 13)
_TA = uuid.uuid4()
_TRUCK = uuid.uuid4()

_TRAINER = uuid.uuid4()
_TRAINEE = uuid.uuid4()
_WALKER = uuid.uuid4()

_NOW = datetime.now(timezone.utc)


def _caller(role="dispatch", emp_id=None):
    c = MagicMock()
    c.id = emp_id or uuid.uuid4()
    c.company_id = _CID
    c.role = role
    return c


def _member(employee_id, role, paired_trainer_id=None, status="active",
            ap_arrived_at=None, trip_count=0):
    return SimpleNamespace(
        id=uuid.uuid4(), employee_id=employee_id, role=role,
        assignment_id=_TA, company_id=_CID, status=status,
        paired_trainer_id=paired_trainer_id, ap_arrived_at=ap_arrived_at,
        trip_count=trip_count,
    )


def _ta():
    return SimpleNamespace(id=_TA, truck_id=_TRUCK, company_id=_CID, date=_DATE)


def _db(members, *, own_member=None, route_first=None):
    """Mock Session. TruckAssignment list → [_ta()]; AssignmentMember list →
    members; Employee names → simple objects; Route/DeliveryStop → none/empty."""
    db = MagicMock()

    def _query(*models):
        from app.models.truck_assignment import TruckAssignment
        from app.models.assignment_member import AssignmentMember
        from app.models.employee import Employee
        from app.models.truck import Truck
        from app.models.walker_route import Route
        from app.models.delivery_stop import DeliveryStop
        model = models[0]
        q = MagicMock()

        def _chain(*a, **k):
            f = MagicMock()
            # allow .filter().filter()… to keep returning the chain
            f.filter.return_value = f
            if model is TruckAssignment:
                f.all.return_value = [_ta()]
                f.first.return_value = _ta()
            elif model is AssignmentMember:
                f.all.return_value = members
                f.first.return_value = own_member
            elif model is Employee:
                f.all.return_value = [
                    SimpleNamespace(id=m.employee_id, name=f"emp-{str(m.employee_id)[:4]}")
                    for m in members
                ]
                f.first.return_value = None
            elif model is Truck:
                f.first.return_value = SimpleNamespace(id=_TRUCK, name="Truck 12", company_id=_CID)
            elif model is Route:
                f.first.return_value = route_first
                f.all.return_value = []
            elif model is DeliveryStop:
                f.count.return_value = 0
                f.all.return_value = []
            else:
                f.first.return_value = None
                f.all.return_value = []
            return f

        q.filter = _chain
        q.join.return_value.filter = _chain
        return q

    db.query = _query
    return db


class TestCrewStatusScope:
    def test_field_caller_without_assignment_404(self):
        from fastapi import HTTPException
        db = _db([_member(_WALKER, "walker")], own_member=None)
        with pytest.raises(HTTPException) as exc:
            get_crew_status(target_date=_DATE, caller=_caller("driver"), _=None, db=db)
        assert exc.value.status_code == 404


class TestCrewStatusEnrichment:
    def _run(self, members, **kw):
        db = _db(members, **kw)
        return get_crew_status(target_date=_DATE, caller=_caller("dispatch"), _=None, db=db)

    def test_trip_count_passed_through(self):
        m = _member(_WALKER, "walker", trip_count=3)
        resp = self._run([m])
        walker = resp.trucks[0].members[0]
        assert walker.trip_count == 3

    def test_pairing_populated_both_directions(self):
        trainer = _member(_TRAINER, "trainer", ap_arrived_at=_NOW)
        trainee = _member(_TRAINEE, "trainee", paired_trainer_id=_TRAINER, ap_arrived_at=_NOW)
        resp = self._run([trainer, trainee])
        by_role = {mm.role: mm for mm in resp.trucks[0].members}
        assert by_role["trainee"].paired_trainer_id == _TRAINER
        assert by_role["trainer"].paired_trainee_id == _TRAINEE

    def test_orphaned_when_trainer_not_arrived_but_trainee_has(self):
        # Trainer active but NOT arrived; trainee arrived → orphaned.
        trainer = _member(_TRAINER, "trainer", ap_arrived_at=None)
        trainee = _member(_TRAINEE, "trainee", paired_trainer_id=_TRAINER, ap_arrived_at=_NOW)
        resp = self._run([trainer, trainee])
        trainee_out = next(mm for mm in resp.trucks[0].members if mm.role == "trainee")
        assert trainee_out.orphaned is True

    def test_not_orphaned_when_both_arrived(self):
        trainer = _member(_TRAINER, "trainer", ap_arrived_at=_NOW)
        trainee = _member(_TRAINEE, "trainee", paired_trainer_id=_TRAINER, ap_arrived_at=_NOW)
        resp = self._run([trainer, trainee])
        trainee_out = next(mm for mm in resp.trucks[0].members if mm.role == "trainee")
        assert trainee_out.orphaned is False

    def test_not_orphaned_before_trainee_arrives(self):
        # Trainer not arrived, trainee ALSO not arrived → pre-shift, not an emergency.
        trainer = _member(_TRAINER, "trainer", ap_arrived_at=None)
        trainee = _member(_TRAINEE, "trainee", paired_trainer_id=_TRAINER, ap_arrived_at=None)
        resp = self._run([trainer, trainee])
        trainee_out = next(mm for mm in resp.trucks[0].members if mm.role == "trainee")
        assert trainee_out.orphaned is False

    def test_orphaned_when_trainer_departed(self):
        trainer = _member(_TRAINER, "trainer", status="departed", ap_arrived_at=_NOW)
        trainee = _member(_TRAINEE, "trainee", paired_trainer_id=_TRAINER, ap_arrived_at=_NOW)
        resp = self._run([trainer, trainee])
        trainee_out = next(mm for mm in resp.trucks[0].members if mm.role == "trainee")
        assert trainee_out.orphaned is True
