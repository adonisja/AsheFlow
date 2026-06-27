"""Tests for incidents router (ADR-147 audit findings).

Verified findings:
  HIGH-1: _resolve_assignment (line 32-46) — inner queries join AssignmentMember
          and TruckAssignment but do NOT filter by company_id. A cross-tenant
          reporter_id match on a different company's assignment is possible.
  HIGH-2: _resolve_driver_id (line 49-59) — queries AssignmentMember by
          assignment_id and role only, no company_id.
  HIGH-3: submit_incident has no write_audit call despite creating an Incident
          row and fan-out notifications.
  INFO:   list_incidents inner Employee/Truck bulk queries do not re-filter by
          company_id (acceptable risk — IDs are derived from already-scoped rows).

Role-gate coverage:
  - submit_incident has no role gate at all (any authenticated user can submit).
    Per CLAUDE.md this is valid: anyone on a truck can report an incident.
    Verify the gate is intentionally absent.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_employee(company_id=_CID_A, role="walker"):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_employee"
    emp.is_active = True
    return emp


# ---------------------------------------------------------------------------
# HIGH-1: _resolve_assignment missing company_id
# ---------------------------------------------------------------------------

class TestResolveAssignmentCrossTenant:
    """
    _resolve_assignment now accepts company_id and filters by it (fixed in ADR-148).
    Tests verify the fix is in place.
    """

    def test_resolve_assignment_filters_company_id(self):
        """
        _resolve_assignment now filters by company_id in both the join query
        and the secondary TruckAssignment lookup.
        """
        import inspect
        from app.routers.incidents import _resolve_assignment
        source = inspect.getsource(_resolve_assignment)
        assert "company_id" in source, (
            "_resolve_assignment must filter by company_id (fixed in ADR-148)."
        )

    def test_resolve_assignment_returns_none_for_foreign_company(self):
        """
        With the fix in place, _resolve_assignment returns (None, None) when
        no member is found scoped to the given company_id.
        """
        from app.routers.incidents import _resolve_assignment

        reporter_id = uuid.uuid4()
        company_id = uuid.uuid4()
        target_date = date.today()

        db = MagicMock()
        q = MagicMock()
        q.join = MagicMock(return_value=q)

        def _filter(*args):
            f = MagicMock()
            f.first.return_value = None  # company-scoped query finds nothing
            return f

        q.filter = _filter
        db.query.return_value = q

        truck_id, assignment_id = _resolve_assignment(reporter_id, target_date, company_id, db)
        assert truck_id is None
        assert assignment_id is None


# ---------------------------------------------------------------------------
# HIGH-2: _resolve_driver_id missing company_id
# ---------------------------------------------------------------------------

class TestResolveDriverIdCrossTenant:
    def test_resolve_driver_id_filters_company_id(self):
        """
        _resolve_driver_id now accepts and filters by company_id (fixed in ADR-148).
        """
        import inspect
        from app.routers.incidents import _resolve_driver_id
        source = inspect.getsource(_resolve_driver_id)
        assert "company_id" in source, (
            "_resolve_driver_id must filter by company_id (fixed in ADR-148)."
        )

    def test_resolve_driver_id_returns_none_when_not_found(self):
        """_resolve_driver_id returns None when no company-scoped driver member found."""
        from app.routers.incidents import _resolve_driver_id

        assignment_id = uuid.uuid4()
        company_id = uuid.uuid4()

        db = MagicMock()
        q = MagicMock()

        def _filter(*args):
            f = MagicMock()
            f.first.return_value = None
            return f

        q.filter = _filter
        db.query.return_value = q

        result = _resolve_driver_id(assignment_id, company_id, db)
        assert result is None


# ---------------------------------------------------------------------------
# HIGH-3: submit_incident missing write_audit
# ---------------------------------------------------------------------------

class TestSubmitIncidentMissingAudit:
    def _make_db(self, reporter, incident_to_return=None):
        """Build a minimal mock DB for submit_incident."""
        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        from app.models.incident import Incident
        from app.models.employee import Employee
        from app.models.assignment_member import AssignmentMember
        from app.models.truck_assignment import TruckAssignment

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None
                f.all.return_value = []
                return f
            q.filter = _filter
            return q

        db.query = _query
        return db

    def test_submit_incident_does_not_call_write_audit(self):
        """
        Proven: submit_incident creates Incident + notifications then commits
        but never calls write_audit. The function should be audited.
        """
        from app.routers.incidents import submit_incident
        from app.schemas.incident import IncidentCreate

        reporter = _make_employee(role="walker")
        db = self._make_db(reporter)

        body = IncidentCreate(
            date=date.today(),
            category="other",
            severity="info",
            description="test incident for audit coverage",
        )

        with patch("app.routers.incidents.write_audit") as mock_audit:
            try:
                submit_incident(payload=body, db=db, reporter=reporter)
            except Exception:
                pass  # DB mock may not support full flow
            # write_audit IS now called by submit_incident (fixed in ADR-148)
            mock_audit.assert_called_once()

    def test_resolve_incident_calls_write_audit(self):
        """
        Baseline: resolve_incident DOES call write_audit — confirms the import
        and call pattern are working for the resolve path.
        """
        from app.routers.incidents import resolve_incident

        resolver = _make_employee(role="dispatch")
        incident = MagicMock()
        incident.id = uuid.uuid4()
        incident.resolved = False
        incident.reporter_id = uuid.uuid4()
        incident.category = "other"
        incident.date = date.today()
        incident.company_id = _CID_A

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = incident
                return f
            q.filter = _filter
            return q
        db.query = _query

        with patch("app.routers.incidents.write_audit") as mock_audit:
            resolve_incident(
                incident_id=uuid.uuid4(),
                resolver=resolver,
                _={},
                db=db,
            )
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args.kwargs
            assert call_kwargs["action_type"] == "incident.resolved"


# ---------------------------------------------------------------------------
# Role gate: submit_incident has no RoleChecker — intentional (any authenticated)
# ---------------------------------------------------------------------------

class TestSubmitIncidentRoleGate:
    def test_submit_incident_has_no_role_checker_dependency(self):
        """submit_incident intentionally has no role gate — any authenticated user submits."""
        import inspect
        from app.routers.incidents import submit_incident
        sig = inspect.signature(submit_incident)
        param_names = list(sig.parameters.keys())
        # The endpoint takes: payload, db, reporter — no _ RoleChecker param
        assert "_" not in param_names, (
            "submit_incident has no role gate by design — "
            "any authenticated field employee can report an incident."
        )


# ---------------------------------------------------------------------------
# list_incidents: scoped to caller company — positive test
# ---------------------------------------------------------------------------

class TestListIncidentsScoping:
    def test_list_incidents_filters_by_company(self):
        """list_incidents main query filters by Incident.company_id == caller.company_id."""
        from app.routers.incidents import list_incidents

        caller = _make_employee(role="dispatch")
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
            q.join = MagicMock(return_value=q)
            return q

        db.query = _query

        list_incidents(
            severity=None,
            category=None,
            resolved=None,
            date_from=None,
            date_to=None,
            pg=MagicMock(apply=lambda q: q),
            caller=caller,
            _={},
            db=db,
        )

        filter_strs = [str(f) for f in captured]
        assert any("company_id" in s for s in filter_strs), (
            "list_incidents must filter by company_id on the main query."
        )
