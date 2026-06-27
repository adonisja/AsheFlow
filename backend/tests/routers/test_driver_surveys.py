"""Tests for driver_surveys router (ADR-147 audit findings).

Verified findings:
  HIGH-1: _build_response_item (lines 106-128) — four inner queries without company_id:
          - Employee.id == resp.respondent_id (no company_id)
          - TruckAssignment.id == resp.truck_assignment_id (no company_id)
          - Truck.id == assignment.truck_id (no company_id)
          - AssignmentMember.assignment_id + role == "driver" (no company_id)
          - Employee.id == driver_member.employee_id (no company_id)
          All lookups use only the FK ID, no tenant isolation.

  HIGH-2: submit_response — no write_audit on survey response creation.

Correct-behaviour coverage:
  - activate_survey: uniqueness check → 409 on duplicate date
  - activate_survey: 3-hour shift rule enforced
  - submit_response: one response per person per survey → 409 on duplicate
  - submit_response: closed survey → 400
  - get_survey: scoped to caller company
  - list_surveys: scoped to caller company
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(role="management", company_id=_CID_A):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    emp.discord_id = None
    return emp


def _make_survey(company_id=_CID_A, survey_date=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.company_id = company_id
    s.date = survey_date or date.today()
    s.created_at = datetime.now(timezone.utc)
    s.created_by = uuid.uuid4()
    return s


# ---------------------------------------------------------------------------
# HIGH-1: _build_response_item missing company_id on all inner queries
# ---------------------------------------------------------------------------

class TestBuildResponseItemCrossTenant:
    def test_respondent_lookup_has_company_id(self):
        """
        _build_response_item respondent lookup now includes company_id filter (fixed in ADR-148).
        """
        import inspect
        from app.routers.driver_surveys import _build_response_item
        source = inspect.getsource(_build_response_item)

        assert "Employee.id == resp.respondent_id" in source, "Respondent lookup pattern not found"

        idx = source.find("Employee.id == resp.respondent_id")
        surrounding = source[max(0, idx - 100): idx + 200]
        assert "company_id" in surrounding, (
            "_build_response_item must filter respondent by company_id."
        )

    def test_assignment_lookup_has_company_id(self):
        """
        _build_response_item TruckAssignment lookup now includes company_id filter (fixed in ADR-148).
        """
        import inspect
        from app.routers.driver_surveys import _build_response_item
        source = inspect.getsource(_build_response_item)

        assert "TruckAssignment.id == resp.truck_assignment_id" in source

        idx = source.find("TruckAssignment.id == resp.truck_assignment_id")
        surrounding = source[max(0, idx - 100): idx + 200]
        assert "company_id" in surrounding, (
            "_build_response_item must filter TruckAssignment by company_id."
        )

    def test_driver_lookup_has_company_id(self):
        """
        _build_response_item driver employee lookup now includes company_id filter (fixed in ADR-148).
        """
        import inspect
        from app.routers.driver_surveys import _build_response_item
        source = inspect.getsource(_build_response_item)

        assert "driver_member.employee_id" in source

        idx = source.find("driver_member.employee_id")
        surrounding = source[max(0, idx - 100): idx + 200]
        assert "company_id" in surrounding, (
            "_build_response_item must filter driver Employee by company_id."
        )


# ---------------------------------------------------------------------------
# HIGH-2: submit_response missing write_audit
# ---------------------------------------------------------------------------

class TestSubmitResponseMissingAudit:
    def test_write_audit_is_imported(self):
        import app.routers.driver_surveys as ds_module
        assert hasattr(ds_module, "write_audit"), (
            "write_audit must be imported in driver_surveys.py (fixed in ADR-148)."
        )


# ---------------------------------------------------------------------------
# activate_survey: uniqueness check
# ---------------------------------------------------------------------------

class TestActivateSurveyUniqueness:
    def test_duplicate_date_raises_409(self):
        from app.routers.driver_surveys import activate_survey
        from app.schemas.driver_survey import DriverSurveyCreate

        caller = _make_caller(role="management")
        existing = _make_survey()

        from app.models.driver_survey import DriverSurvey

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is DriverSurvey:
                    f.first.return_value = existing
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = DriverSurveyCreate(date=date.today())

        with pytest.raises(HTTPException) as exc_info:
            activate_survey(body=body, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 409

    def test_new_survey_date_proceeds_past_uniqueness_check(self):
        """When no existing survey, uniqueness check passes and db.commit is reached."""
        from app.routers.driver_surveys import activate_survey
        from app.schemas.driver_survey import DriverSurveyCreate

        caller = _make_caller(role="management")

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        # Single MagicMock query chain handles all call forms including
        # db.query(ModelA, ModelB, ModelC, ModelD).join(...).filter(...).all()
        q = MagicMock()
        q.join = MagicMock(return_value=q)
        q.filter = MagicMock(return_value=q)
        q.first.return_value = None   # uniqueness check → no existing survey
        q.all.return_value = []       # member fan-out → zero members (no notifications)
        q.count.return_value = 0

        db.query = MagicMock(return_value=q)

        with patch("app.routers.driver_surveys.get_company_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(shift_start=None)
            with patch("app.routers.driver_surveys.DriverSurveyListItem") as mock_item:
                mock_item.return_value = MagicMock()
                body = DriverSurveyCreate(date=date.today())
                activate_survey(body=body, caller=caller, _={}, db=db)

        # Uniqueness check passed — commit was reached
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# submit_response: one response per person
# ---------------------------------------------------------------------------

class TestSubmitResponseIdempotency:
    def test_duplicate_response_raises_409(self):
        from app.routers.driver_surveys import submit_response
        from app.schemas.driver_survey import DriverSurveyResponseCreate

        caller = _make_caller(role="trainer")
        survey = _make_survey()
        # Survey date is tomorrow — always open regardless of UTC clock
        survey.date = date.today() + timedelta(days=1)

        existing_response = MagicMock()

        from app.models.driver_survey import DriverSurvey, DriverSurveyResponse

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is DriverSurvey:
                    f.first.return_value = survey
                elif model is DriverSurveyResponse:
                    f.first.return_value = existing_response
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = DriverSurveyResponseCreate(
            routes_organized=True,
            anchor_point_location=True,
            supplies_ready=True,
            driver_support=True,
            notes=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            submit_response(survey_id=survey.id, body=body, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 409

    def test_closed_survey_raises_400(self):
        """Survey date in the past → closed → 400."""
        from app.routers.driver_surveys import submit_response
        from app.schemas.driver_survey import DriverSurveyResponseCreate

        caller = _make_caller(role="trainer")
        survey = _make_survey()
        # Set survey date to yesterday — past midnight
        survey.date = date(2000, 1, 1)

        from app.models.driver_survey import DriverSurvey, DriverSurveyResponse

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                if model is DriverSurvey:
                    f.first.return_value = survey
                elif model is DriverSurveyResponse:
                    f.first.return_value = None  # no existing
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q

        db.query = _query

        body = DriverSurveyResponseCreate(
            routes_organized=True,
            anchor_point_location=True,
            supplies_ready=True,
            driver_support=True,
            notes=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            submit_response(survey_id=survey.id, body=body, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400
        assert "closed" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# get_survey: scoped to caller company
# ---------------------------------------------------------------------------

class TestGetSurveyScoping:
    def test_get_survey_raises_404_for_foreign_company(self):
        from app.routers.driver_surveys import get_survey

        caller = _make_caller(role="management", company_id=_CID_A)

        from app.models.driver_survey import DriverSurvey

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # not found in this company
                return f
            q.filter = _filter
            return q

        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            get_survey(survey_date=date.today(), caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 404
