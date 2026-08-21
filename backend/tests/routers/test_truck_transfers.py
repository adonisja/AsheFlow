"""Tests for truck_transfers router (ADR-147 audit findings).

Verified findings:
  HIGH-1: to_truck lookup (line 174):
          db.query(Truck).filter(Truck.id == body.to_truck_id).first()
          — no company_id filter. Could resolve a truck from another tenant.

  HIGH-2: paired trainee lookup (lines 198-207):
          db.query(AssignmentMember).filter(
              AssignmentMember.assignment_id == am.assignment_id,
              AssignmentMember.paired_trainer_id == eid,
          ).all()
          — no company_id filter.

  HIGH-3: no write_audit on transfer creation.

  HIGH-4: get_my_transfers inner lookups (lines 341-344) — TruckAssignment and
          Truck fetched without company_id; relying on outer filter only.

Correct-behaviour coverage:
  - transfers to a planned (unpublished) truck raise 409
  - transfers from a planned truck produce a warning (not block)
  - employees already on destination truck produce a warning (not block)
  - non-transferable roles (driver, dispatch, etc.) produce a warning
  - get_transfers scoped to caller.company_id
  - get_my_transfers scoped to caller.id + company_id
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(role="dispatch", company_id=_CID_A):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    emp.discord_id = None
    return emp


def _make_truck(company_id=_CID_A, name="Truck A"):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.company_id = company_id
    t.name = name
    t.discord_channel_id = None
    return t


def _make_ta(truck_id=None, company_id=_CID_A, status="dispatched"):
    ta = MagicMock()
    ta.id = uuid.uuid4()
    ta.company_id = company_id
    ta.truck_id = truck_id or uuid.uuid4()
    ta.status = status
    ta.date = date.today()
    return ta


# ---------------------------------------------------------------------------
# HIGH-1: to_truck lookup missing company_id
# ---------------------------------------------------------------------------

class TestToTruckCrossTenant:
    """
    to_truck lookup now includes Truck.company_id == caller.company_id (fixed in ADR-148).
    """

    def test_to_truck_lookup_has_company_id_filter(self):
        """Verify the fix: to_truck lookup now filters by company_id."""
        import inspect
        from app.routers.truck_transfers import create_transfers
        source = inspect.getsource(create_transfers)

        assert "Truck.id == body.to_truck_id" in source, "to_truck lookup line not found"
        idx = source.find("Truck.id == body.to_truck_id")
        surrounding = source[max(0, idx - 50): idx + 200]
        assert "company_id" in surrounding, (
            "to_truck lookup must filter by Truck.company_id (fixed in ADR-148)."
        )


# ---------------------------------------------------------------------------
# HIGH-2: paired trainee lookup — company_id now present
# ---------------------------------------------------------------------------

class TestPairedTraineeLookupCrossTenant:
    def test_paired_trainee_query_has_company_id(self):
        """
        paired_trainer_id lookup now includes AssignmentMember.company_id filter
        (fixed in ADR-148).
        """
        import inspect
        from app.routers.truck_transfers import create_transfers
        source = inspect.getsource(create_transfers)

        assert "paired_trainer_id == eid" in source
        idx = source.find("paired_trainer_id == eid")
        surrounding = source[max(0, idx - 200): idx + 200]
        assert "company_id" in surrounding, (
            "paired trainee lookup must filter by AssignmentMember.company_id (fixed in ADR-148)."
        )


# ---------------------------------------------------------------------------
# HIGH-3: write_audit missing from create_transfers
# ---------------------------------------------------------------------------

class TestTruckTransfersMissingAudit:
    def test_write_audit_is_imported(self):
        """write_audit is now imported in truck_transfers.py (fixed in ADR-148)."""
        import app.routers.truck_transfers as tt
        assert hasattr(tt, "write_audit"), (
            "write_audit must be imported in truck_transfers.py."
        )


# ---------------------------------------------------------------------------
# Correct-behaviour: destination truck planned → 409
# ---------------------------------------------------------------------------

class TestCreateTransferDestinationPlanned:
    def test_transfer_to_planned_truck_raises_409(self):
        from app.routers.truck_transfers import create_transfers

        caller = _make_caller()
        to_truck = _make_truck()
        to_ta = _make_ta(truck_id=to_truck.id, status="planned")  # not published

        db = MagicMock()

        from app.models.truck_assignment import TruckAssignment
        from app.models.truck import Truck

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                if model is TruckAssignment:
                    f.first.return_value = to_ta
                elif model is Truck:
                    f.first.return_value = to_truck
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = MagicMock()
        body.to_truck_id = to_truck.id
        body.date = date.today()
        body.employee_ids = []
        body.note = None

        with pytest.raises(HTTPException) as exc_info:
            create_transfers(body=body, _={}, caller=caller, db=db)
        assert exc_info.value.status_code == 409

    def test_transfer_when_no_destination_assignment_raises_404(self):
        from app.routers.truck_transfers import create_transfers

        caller = _make_caller()

        db = MagicMock()
        q = MagicMock()
        q.join = MagicMock(return_value=q)

        def _filter(*args):
            f = MagicMock()
            f.first.return_value = None  # no assignment found
            return f

        q.filter = _filter
        db.query.return_value = q

        body = MagicMock()
        body.to_truck_id = uuid.uuid4()
        body.date = date.today()
        body.employee_ids = []
        body.note = None

        with pytest.raises(HTTPException) as exc_info:
            create_transfers(body=body, _={}, caller=caller, db=db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Non-transferable role produces warning (not block)
# ---------------------------------------------------------------------------

class TestNonTransferableRole:
    def test_driver_produces_warning_not_error(self):
        from app.routers.truck_transfers import create_transfers, TRANSFERABLE_ROLES

        assert "driver" not in TRANSFERABLE_ROLES
        assert "dispatch" not in TRANSFERABLE_ROLES

        caller = _make_caller()
        driver_id = uuid.uuid4()
        to_truck = _make_truck(name="Truck B")
        to_ta = _make_ta(truck_id=to_truck.id, status="dispatched")

        driver_emp = MagicMock()
        driver_emp.id = driver_id
        driver_emp.company_id = _CID_A
        driver_emp.role = "driver"
        driver_emp.name = "Driver Dan"
        driver_emp.discord_id = None

        from app.models.truck_assignment import TruckAssignment
        from app.models.assignment_member import AssignmentMember
        from app.models.employee import Employee
        from app.models.truck import Truck

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                if model is TruckAssignment:
                    f.first.return_value = to_ta
                elif model is Truck:
                    f.first.return_value = to_truck
                elif model is Employee:
                    f.first.return_value = driver_emp
                elif model is AssignmentMember:
                    f.first.return_value = None
                    f.all.return_value = []
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db = MagicMock()
        db.query = _query
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()

        body = MagicMock()
        body.to_truck_id = to_truck.id
        body.date = date.today()
        body.employee_ids = [driver_id]
        body.note = None

        result = create_transfers(body=body, _={}, caller=caller, db=db)
        assert any("cannot be transferred" in w for w in result.warnings)
        assert result.transfers == []


# ---------------------------------------------------------------------------
# get_transfers scoped to company
# ---------------------------------------------------------------------------

class TestGetTransfersScoping:
    def test_get_transfers_filters_by_company(self):
        from app.routers.truck_transfers import get_transfers

        caller = _make_caller()
        captured = []

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                captured.extend(args)
                f = MagicMock()
                f.order_by = MagicMock(return_value=f)
                f.all.return_value = []
                return f
            q.filter = _filter
            return q

        db.query = _query

        get_transfers(date=date.today(), _={}, caller=caller, db=db)

        filter_strs = [str(f) for f in captured]
        assert any("company_id" in s for s in filter_strs)


# ---------------------------------------------------------------------------
# get_my_transfers scoped to caller
# ---------------------------------------------------------------------------

class TestGetMyTransfersScoping:
    def test_get_my_transfers_filters_by_employee_and_company(self):
        from app.routers.truck_transfers import get_my_transfers

        caller = _make_caller()
        captured = []

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                captured.extend(args)
                f = MagicMock()
                f.order_by = MagicMock(return_value=f)
                f.all.return_value = []
                return f
            q.filter = _filter
            return q

        db.query = _query
        get_my_transfers(date=date.today(), caller=caller, db=db)

        filter_strs = [str(f) for f in captured]
        assert any("company_id" in s for s in filter_strs)
        assert any("employee_id" in s for s in filter_strs)


# ---------------------------------------------------------------------------
# ADR-197 — transfer updates AssignmentMember rosters
# ---------------------------------------------------------------------------

class TestTransferUpdatesRoster:
    """A successful transfer marks the SOURCE member 'transferred' and adds an
    active member on the DESTINATION, so /dispatch assigned_crews (built from
    AssignmentMember) reflects the transfer on both trucks (ADR-197)."""

    @patch("app.routers.truck_transfers._fire_transfer_discord", MagicMock())
    def test_source_stamped_and_destination_added(self):
        from app.routers.truck_transfers import create_transfers, TransferOut
        from app.models.truck_assignment import TruckAssignment
        from app.models.assignment_member import AssignmentMember
        from app.models.employee import Employee
        from app.models.truck import Truck
        from app.models.truck_transfer import TruckTransfer

        caller = _make_caller()
        emp_id = uuid.uuid4()
        from_truck = _make_truck(name="Truck A")
        to_truck   = _make_truck(name="Truck B")
        from_ta = _make_ta(truck_id=from_truck.id, status="dispatched")
        to_ta   = _make_ta(truck_id=to_truck.id,   status="dispatched")

        emp = MagicMock(id=emp_id, company_id=_CID_A, role="walker",
                        name="Wanda Walker", discord_id=None)

        # A real-ish source member whose attributes we assert after.
        from_am = MagicMock(assignment_id=from_ta.id, employee_id=emp_id,
                            company_id=_CID_A, role="walker", paired_trainer_id=None,
                            status="active", departed_at=None)

        # TruckAssignment.first(): to_ta (initial 'to' lookup), then from_ta (in loop).
        ta_firsts = [to_ta, from_ta]

        # AssignmentMember lookups that .join(TruckAssignment) are the source/
        # pre-pass member lookups → return from_am. The destination-existence
        # check does NOT join (filters assignment_id directly) → return None so a
        # new member is added.
        def _query(model):
            q = MagicMock()
            q._joined = False
            def _join(*a, **k):
                q._joined = True
                return q
            q.join = _join
            def _filter(*args):
                f = MagicMock()
                if model is TruckAssignment:
                    f.first.side_effect = lambda: ta_firsts.pop(0) if ta_firsts else from_ta
                elif model is Truck:
                    f.first.return_value = to_truck
                elif model is Employee:
                    f.first.return_value = emp
                elif model is AssignmentMember:
                    f.first.return_value = from_am if q._joined else None
                    f.all.return_value = []
                elif model is TruckTransfer:
                    f.first.return_value = None
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        added = []
        db = MagicMock()
        db.query = _query
        db.add = MagicMock(side_effect=lambda o: added.append(o))
        db.flush = MagicMock(); db.commit = MagicMock()

        body = MagicMock(to_truck_id=to_truck.id, date=date.today(),
                         employee_ids=[emp_id], note=None)

        _stub_out = TransferOut(
            id=uuid.uuid4(), employee_id=emp_id, employee_name="Wanda Walker",
            from_truck_name="Truck A", to_truck_name="Truck B",
            transfer_date=date.today(), transferred_at="2026-07-12T00:00:00", note=None,
        )
        with patch("app.routers.truck_transfers._build_out", return_value=_stub_out):
            create_transfers(body=body, _={}, caller=caller, db=db)

        # source stamped transferred
        assert from_am.status == "transferred"
        assert from_am.departed_at is not None
        # an active AssignmentMember added on the destination
        added_members = [o for o in added if isinstance(o, AssignmentMember)]
        assert len(added_members) == 1
        assert added_members[0].assignment_id == to_ta.id
        assert added_members[0].status == "active"
        assert added_members[0].employee_id == emp_id
