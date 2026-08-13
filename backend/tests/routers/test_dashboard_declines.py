"""The decline-analysis endpoint and its access gate (ADR-268).

WHY THIS ENDPOINT IS MANAGEMENT+ADMIN AND NOT DISPATCH
`by_person` is a named list of who declines most. That is individual
performance data, and docs/SCORECARD_ACCESS_MODEL.md places individual data
with management — dispatch sees company-level surfaces only. The Scorecards
page already filters its sub-tabs on exactly that rule; a second, looser rule
here would make the same data reachable by a role denied it one page over.

WHAT THESE TESTS PIN
  1. the role gate is declared (not just "works today because nobody tried")
  2. the gate is the MANAGEMENT one, not the dispatch one
  3. the service result survives Pydantic serialization
  4. a gated slice arrives as `rate: null`, not 0.0

(4) is the one that matters most over the wire. The service returning None is
worthless if the schema coerces it to 0.0 on the way out, because the client
then cannot tell "no data" from "zero percent" — and 0.0 is the value that gets
quoted in a meeting.
"""
import inspect
import uuid
from datetime import date, timedelta

import pytest

from app.routers import dashboards
from app.models.dispatch_confirmation import DispatchConfirmation
from app.schemas.dashboard_summaries import DeclineAnalysisOut
from app.services.decline_analysis import get_decline_analysis
from tests.conftest import SEED_COMPANY_ID, make_employee


def _conf(db, employee, when, status):
    db.add(DispatchConfirmation(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=employee.id,
        date=when, status=status, source="manual",
    ))
    db.commit()


def _fridays(n):
    d = date.today()
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return [d - timedelta(weeks=i) for i in reversed(range(n))]


class TestAccessGate:
    def test_endpoint_declares_a_role_gate(self):
        src = inspect.getsource(dashboards.management_declines)
        assert "Depends(" in src and "allow_" in src, (
            "decline analysis is ungated — by_person names who declines most"
        )

    def test_gate_is_management_not_dispatch(self):
        """Dispatch must not reach the per-person slice. If this flips to
        allow_dispatch, a role denied individual data on the Scorecards page
        can read the same thing here."""
        src = inspect.getsource(dashboards.management_declines)
        assert "allow_management" in src
        assert "allow_dispatch" not in src

    def test_it_is_company_scoped_via_caller(self):
        """The service takes company_id as an argument, so the router passing
        caller.company_id IS the tenant boundary for this endpoint."""
        src = inspect.getsource(dashboards.management_declines)
        assert "caller.company_id" in src


class TestSerializationPreservesTheGate:
    def test_gated_slice_serializes_as_null_not_zero(self, db):
        """The whole point of `rate: None` is lost if the schema emits 0.0.

        Three Fridays is below MIN_WEEKDAY_OCCURRENCES, so this slice must
        cross the wire with rate=null and gated=true.
        """
        emp = make_employee(db, role="walker", name="Fri Decliner")
        for d in _fridays(3):
            _conf(db, emp, d, "declined")

        result = get_decline_analysis(
            db, SEED_COMPANY_ID, date.today() - timedelta(days=60), date.today()
        )
        out = DeclineAnalysisOut.model_validate(result, from_attributes=True)

        fri = next(s for s in out.by_weekday if s.key == "Friday")
        assert fri.gated is True
        assert fri.rate is None, "gated rate became a number in the response"

        # And in the actual JSON payload, since that is what the client parses.
        payload = out.model_dump(mode="json")
        fri_json = next(s for s in payload["by_weekday"] if s["key"] == "Friday")
        assert fri_json["rate"] is None
        assert fri_json["declines"] == 3

    def test_ungated_slice_serializes_a_real_rate(self, db):
        """The counterpart: once the gate clears, the rate must survive."""
        emp = make_employee(db, role="walker", name="Fri Decliner 2")
        for d in _fridays(4):
            _conf(db, emp, d, "declined")

        result = get_decline_analysis(
            db, SEED_COMPANY_ID, date.today() - timedelta(days=60), date.today()
        )
        out = DeclineAnalysisOut.model_validate(result, from_attributes=True)

        fri = next(s for s in out.by_weekday if s.key == "Friday")
        assert fri.gated is False
        assert fri.rate == 1.0

    def test_nested_slices_have_from_attributes(self):
        """A nested model without from_attributes 500s the endpoint at
        response time while every service-level test still passes — that
        exact bug shipped once already this cycle (56687cf)."""
        from app.schemas.dashboard_summaries import DeclineSlice
        assert DeclineSlice.model_config.get("from_attributes") is True
        assert DeclineAnalysisOut.model_config.get("from_attributes") is True