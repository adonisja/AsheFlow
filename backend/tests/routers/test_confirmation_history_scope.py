"""Who may read whose confirmation history (ADR-268).

WHAT WENT WRONG
GET /dispatch/confirmations/history returns every employee's confirmation
records for a date range — who declined, when, how often. It was gated only by
`get_caller_employee`, so ANY authenticated employee could enumerate the whole
roster's decline history. Company-scoped, but neither role- nor self-scoped.

Its docstring says "for analytics", so field staff were never the intended
audience; the gate was simply missing. ADR-115 D7 flags exactly this shape —
a named-reputation surface — around WalkerRating and MyPerformance.

These are source-level checks. The endpoints live in a proprietary router that
is absent from the public checkout, and the local container mounts only 6
routes, so an HTTP-level test cannot run in every environment. What must not
regress is the *gate declaration* and the *self-scoping filter*, and both are
visible in the source.
"""
import inspect

import pytest

dispatch_router = pytest.importorskip(
    "app.routers.dispatch",
    reason="proprietary router not present in this checkout",
)


class TestRosterWideHistoryIsGated:
    def test_it_requires_dispatch_or_management(self):
        src = inspect.getsource(dispatch_router.get_confirmation_history)
        assert "allow_dispatch_mgmt" in src, (
            "roster-wide confirmation history is ungated again — any "
            "authenticated employee can read every colleague's declines"
        )

    def test_it_is_company_scoped(self):
        src = inspect.getsource(dispatch_router.get_confirmation_history)
        assert "company_id == caller.company_id" in src


class TestSelfScopedHistory:
    def test_it_filters_to_the_caller(self):
        """The employee_id filter IS the authorisation here — there is no role
        gate, so if this filter goes the endpoint becomes the ungated
        roster-wide read all over again."""
        src = inspect.getsource(dispatch_router.get_my_confirmation_history)
        assert "employee_id == caller.id" in src
        assert "company_id == caller.company_id" in src

    def test_it_takes_no_employee_parameter(self):
        """A caller must not be able to widen the scope by naming someone
        else. The signature is the guarantee."""
        sig = inspect.signature(dispatch_router.get_my_confirmation_history)
        for name in sig.parameters:
            assert "employee" not in name.lower(), (
                f"parameter {name!r} could let a caller read another person's "
                "history"
            )

    def test_it_does_not_return_the_employee_id(self):
        """Returning it would be harmless but pointless — the caller knows who
        they are — and its absence makes accidental reuse of this shape for a
        roster-wide response obvious."""
        src = inspect.getsource(dispatch_router.get_my_confirmation_history)
        body = src.split("return")[-1]
        assert "employee_id" not in body


class TestTheTwoEndpointsStayDistinct:
    def test_the_self_scoped_route_exists_separately(self):
        """The fix is only complete with BOTH halves: gating the roster-wide
        read without a self-service alternative would remove a legitimate
        capability rather than a leak."""
        assert hasattr(dispatch_router, "get_my_confirmation_history")
        assert hasattr(dispatch_router, "get_confirmation_history")

    def test_path_parameters_cannot_shadow_the_literal_routes(self):
        """`/{dispatch_date}` is declared ~2600 lines earlier than
        `/confirmations/history`. It does not shadow it — a path parameter
        matches exactly ONE segment — but that is worth pinning, because the
        failure would be a 422 on a date parse rather than an obvious 404."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from datetime import date as _date

        app = FastAPI()

        @app.get("/d/{dispatch_date}")
        def dated(dispatch_date: _date):
            return {"hit": "dated"}

        @app.get("/d/confirmations/history")
        def hist():
            return {"hit": "history"}

        @app.get("/d/confirmations/history/me")
        def mine():
            return {"hit": "me"}

        c = TestClient(app)
        assert c.get("/d/2026-08-07").json() == {"hit": "dated"}
        assert c.get("/d/confirmations/history").json() == {"hit": "history"}
        assert c.get("/d/confirmations/history/me").json() == {"hit": "me"}
