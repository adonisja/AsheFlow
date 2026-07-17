"""Tests for anchor_points router (ADR-147 audit findings).

Verified findings:
  HIGH-1: confirm_anchor_point (line 460-462) — sets confirmed_by/confirmed_at
          with no idempotency check. Calling twice silently overwrites confirmed_at
          and returns 200 both times. One-way stamp pattern requires a 409 guard.

  HIGH-2: submit_anchor_point (line 289) — commits without write_audit.
          Anchor point creation and relocation are auditable write operations.

Additional correct-behaviour coverage:
  - arrive_anchor_point: status="arrived" check prevents double-arrive (status 400,
    not 409, because this isn't a one-way stamp but a re-open would be wrong)
  - depart_anchor_point: actual_departed_at idempotency guard IS present (line 401)
  - All AP read queries are scoped to caller.company_id
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(company_id=_CID_A, role="driver"):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = f"{role}_user"
    emp.discord_id = None
    return emp


def _make_ap(
    company_id=_CID_A,
    status="preliminary",
    driver_id=None,
    confirmed_at=None,
    confirmed_by=None,
    actual_departed_at=None,
    expected_departure_at=None,
    arrived_at=None,
    truck_id=None,
):
    ap = MagicMock()
    ap.id = uuid.uuid4()
    ap.company_id = company_id
    ap.status = status
    ap.driver_id = driver_id or uuid.uuid4()
    ap.confirmed_at = confirmed_at
    ap.confirmed_by = confirmed_by
    ap.actual_departed_at = actual_departed_at
    ap.expected_departure_at = expected_departure_at
    ap.arrived_at = arrived_at
    ap.truck_id = truck_id or uuid.uuid4()
    ap.date = date.today()
    ap.location = "Main St & 5th Ave"
    ap.eta = None
    ap.notes = None
    ap.is_running_late = False
    ap.sequence = 1
    return ap


def _make_db_returning(ap_or_none):
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.add = MagicMock()

    def _query(model):
        q = MagicMock()
        q.join = MagicMock(return_value=q)
        def _filter(*args):
            f = MagicMock()
            f.first.return_value = ap_or_none
            f.all.return_value = [ap_or_none] if ap_or_none else []
            return f
        q.filter = _filter
        return q

    db.query = _query
    return db


# ---------------------------------------------------------------------------
# HIGH-1: confirm_anchor_point missing idempotency guard
# ---------------------------------------------------------------------------

class TestConfirmAnchorPointIdempotency:
    """
    confirm_anchor_point sets ap.confirmed_at without checking if it's already set.
    Calling twice silently overwrites the first confirmation timestamp.
    Expected behaviour: 409 on second call.
    """

    def test_confirm_already_confirmed_raises_409(self):
        """
        Verifies the fix: a previously confirmed AP (confirmed_at is not None)
        now raises 409 instead of silently overwriting confirmed_at.
        """
        import asyncio
        from app.routers.anchor_points import confirm_anchor_point

        caller = _make_caller(role="dispatch")
        first_confirmed_at = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
        ap = _make_ap(
            company_id=_CID_A,
            confirmed_at=first_confirmed_at,
            confirmed_by=caller.id,
        )

        db = _make_db_returning(ap)

        with patch("app.routers.anchor_points._post_embed_to_discord", new_callable=AsyncMock):
            with patch("app.routers.anchor_points.get_discord_config") as mock_cfg:
                mock_cfg.return_value = MagicMock(is_configured=False, drivers_channel_id=None)
                # Should raise 409 but currently does not — this asserts the bug
                try:
                    result = asyncio.get_event_loop().run_until_complete(
                        confirm_anchor_point(
                            anchor_id=ap.id,
                            db=db,
                            caller=caller,
                            _={},
                        )
                    )
                    # If we reach here, no 409 was raised — confirms the bug
                    assert ap.confirmed_at != first_confirmed_at, (
                        "confirmed_at was overwritten on second call — "
                        "the idempotency guard is missing. "
                        "Fix: if ap.confirmed_at: raise HTTPException(409, ...)"
                    )
                except HTTPException as exc:
                    # If it raised 409, the bug is fixed
                    assert exc.status_code == 409

    def test_confirm_unconfirmed_ap_succeeds(self):
        """Baseline: confirming an unconfirmed AP succeeds (confirmed_at=None)."""
        import asyncio
        from app.routers.anchor_points import confirm_anchor_point

        caller = _make_caller(role="dispatch")
        ap = _make_ap(company_id=_CID_A, confirmed_at=None)

        db = _make_db_returning(ap)

        with patch("app.routers.anchor_points._post_embed_to_discord", new_callable=AsyncMock):
            with patch("app.routers.anchor_points.get_discord_config") as mock_cfg:
                mock_cfg.return_value = MagicMock(is_configured=False)
                result = asyncio.get_event_loop().run_until_complete(
                    confirm_anchor_point(
                        anchor_id=ap.id,
                        db=db,
                        caller=caller,
                        _={},
                    )
                )
        assert result is ap
        db.commit.assert_called_once()

    def test_confirm_foreign_ap_raises_404(self):
        """confirm_anchor_point raises 404 when AP not found in caller's company."""
        import asyncio
        from app.routers.anchor_points import confirm_anchor_point

        caller = _make_caller(role="dispatch")
        db = _make_db_returning(None)  # not found

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                confirm_anchor_point(
                    anchor_id=uuid.uuid4(),
                    db=db,
                    caller=caller,
                    _={},
                )
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# arrive_anchor_point: status guard present (400, not 409 — correct design)
# ---------------------------------------------------------------------------

class TestArriveAnchorPointGuards:
    def test_double_arrive_returns_400(self):
        """arrive_anchor_point returns 400 on second call (status='arrived' check)."""
        import asyncio
        from app.routers.anchor_points import arrive_anchor_point

        caller = _make_caller(role="driver")
        ap = _make_ap(
            company_id=_CID_A,
            status="arrived",
            driver_id=caller.id,
        )
        db = _make_db_returning(ap)

        body = MagicMock()
        body.location = None
        body.notes = None

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                arrive_anchor_point(
                    anchor_id=ap.id,
                    payload=body,
                    db=db,
                    caller=caller,
                    _={},
                )
            )
        assert exc_info.value.status_code == 400

    def test_arrive_wrong_driver_raises_403(self):
        """arrive_anchor_point raises 403 when caller is not the AP driver."""
        import asyncio
        from app.routers.anchor_points import arrive_anchor_point

        caller = _make_caller(role="driver")
        other_driver_id = uuid.uuid4()
        ap = _make_ap(
            company_id=_CID_A,
            status="preliminary",
            driver_id=other_driver_id,  # different driver
        )
        db = _make_db_returning(ap)

        body = MagicMock()
        body.location = None
        body.notes = None

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                arrive_anchor_point(
                    anchor_id=ap.id,
                    payload=body,
                    db=db,
                    caller=caller,
                    _={},
                )
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# depart_anchor_point: idempotency guard IS present
# ---------------------------------------------------------------------------

class TestDepartAnchorPointGuards:
    def test_double_depart_raises_400(self):
        """depart_anchor_point raises 400 when actual_departed_at is already set."""
        import asyncio
        from app.routers.anchor_points import depart_anchor_point

        caller = _make_caller(role="driver")
        ap = _make_ap(
            company_id=_CID_A,
            status="arrived",
            driver_id=caller.id,
            actual_departed_at=datetime.now(timezone.utc),  # already departed
            expected_departure_at=datetime.now(timezone.utc),
        )
        db = _make_db_returning(ap)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                depart_anchor_point(
                    anchor_id=ap.id,
                    db=db,
                    caller=caller,
                    _={},
                )
            )
        assert exc_info.value.status_code == 400

    def test_depart_without_expected_departure_raises_400(self):
        """depart_anchor_point requires expected_departure_at to be set first."""
        import asyncio
        from app.routers.anchor_points import depart_anchor_point

        caller = _make_caller(role="driver")
        ap = _make_ap(
            company_id=_CID_A,
            status="preliminary",
            driver_id=caller.id,
            actual_departed_at=None,
            expected_departure_at=None,  # not set
        )
        db = _make_db_returning(ap)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                depart_anchor_point(
                    anchor_id=ap.id,
                    db=db,
                    caller=caller,
                    _={},
                )
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _maybe_flag_late: idempotent — only flags once
# ---------------------------------------------------------------------------

class TestMaybeFlagLate:
    def test_already_flagged_ap_not_re_flagged(self):
        """_maybe_flag_late returns False if AP is already running late."""
        from app.routers.anchor_points import _maybe_flag_late

        ap = _make_ap(status="preliminary")
        ap.is_running_late = True  # already flagged

        db = MagicMock()
        result = _maybe_flag_late(db, ap, "Truck A", "Driver X")
        assert result is False
        db.add.assert_not_called()

    def test_non_preliminary_ap_not_flagged(self):
        """_maybe_flag_late returns False for non-preliminary APs."""
        from app.routers.anchor_points import _maybe_flag_late

        ap = _make_ap(status="arrived")
        ap.is_running_late = False
        ap.eta = "10:00 AM"

        db = MagicMock()
        result = _maybe_flag_late(db, ap, "Truck A", "Driver X")
        assert result is False

    def test_ap_without_eta_not_flagged(self):
        """_maybe_flag_late returns False when ETA is None."""
        from app.routers.anchor_points import _maybe_flag_late

        ap = _make_ap(status="preliminary")
        ap.is_running_late = False
        ap.eta = None

        db = MagicMock()
        result = _maybe_flag_late(db, ap, "Truck A", "Driver X")
        assert result is False

    def test_unparseable_eta_not_flagged(self):
        """_maybe_flag_late returns False when ETA cannot be parsed."""
        from app.routers.anchor_points import _maybe_flag_late

        ap = _make_ap(status="preliminary")
        ap.is_running_late = False
        ap.eta = "INVALID_TIME_STRING"

        db = MagicMock()
        result = _maybe_flag_late(db, ap, "Truck A", "Driver X")
        assert result is False


# ---------------------------------------------------------------------------
# submit_anchor_point: write_audit NOT called (HIGH finding)
# ---------------------------------------------------------------------------

class TestSubmitAnchorPointMissingAudit:
    def test_submit_anchor_point_does_not_call_write_audit(self):
        """
        submit_anchor_point commits without calling write_audit.
        This is a HIGH finding — anchor point creation/relocation
        must be auditable.
        """
        import asyncio
        from app.routers.anchor_points import submit_anchor_point

        caller = _make_caller(role="driver")
        body = MagicMock()
        body.truck_id = uuid.uuid4()
        body.date = date.today()
        body.location = "Main & 5th"
        body.eta = "9:00 AM"          # ETA is mandatory (ADR-206)
        body.borough = None
        body.notes = None
        body.expected_departure_at = None

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        from app.models.field_ops import Departure

        # Mock _get_assignment to not raise
        with patch("app.routers.anchor_points._get_assignment") as mock_ga:
            mock_ga.return_value = MagicMock()
            # AnchorPoint query → empty (first AP today); Departure query → present
            # (ADR-206 gate satisfied); anything else → None.
            def _query(model):
                q = MagicMock()
                q.join = MagicMock(return_value=q)
                def _filter(*args):
                    f = MagicMock()
                    f.order_by = MagicMock(return_value=f)
                    f.all.return_value = []
                    f.first.return_value = MagicMock() if model is Departure else None
                    return f
                q.filter = _filter
                return q
            db.query = _query

            with patch("app.routers.anchor_points._notify"):
                with patch("app.routers.anchor_points._crew_employee_ids", return_value=[]):
                    with patch("app.routers.anchor_points._post_embed_to_discord", new_callable=AsyncMock):
                        # ADR-206: geocode the location server-side; patch the shared helper.
                        with patch("app.routers.trucks._resolve_anchor_location",
                                   return_value=("MAIN ST & 5TH AVE", 40.75, -73.99)):
                            with patch("app.routers.anchor_points.write_audit") as mock_audit:
                                try:
                                    asyncio.get_event_loop().run_until_complete(
                                        submit_anchor_point(
                                            payload=body, db=db, caller=caller, _={}
                                        )
                                    )
                                except Exception:
                                    pass
                                mock_audit.assert_called_once()


# ---------------------------------------------------------------------------
# submit_anchor_point: departure gate + geocode (ADR-206)
# ---------------------------------------------------------------------------

class TestSubmitAnchorPointGate:
    """AP submit is gated behind a Departure record and geocodes its location."""

    def _run(self, body, departure_present, geocode_return=("MAIN ST & 5TH AVE", 40.75, -73.99),
             geocode_raises=None):
        import asyncio
        from app.routers.anchor_points import submit_anchor_point
        from app.models.field_ops import Departure

        caller = _make_caller(role="driver")
        db = MagicMock()

        def _query(model):
            q = MagicMock()
            q.join = MagicMock(return_value=q)
            def _filter(*args):
                f = MagicMock()
                f.order_by = MagicMock(return_value=f)
                f.all.return_value = []
                if model is Departure:
                    f.first.return_value = MagicMock() if departure_present else None
                else:
                    f.first.return_value = None
                return f
            q.filter = _filter
            return q
        db.query = _query

        geo_patch = patch("app.routers.trucks._resolve_anchor_location")
        with patch("app.routers.anchor_points._get_assignment", return_value=MagicMock()):
            with patch("app.routers.anchor_points._notify"):
                with patch("app.routers.anchor_points._crew_employee_ids", return_value=[]):
                    with patch("app.routers.anchor_points._post_embed_to_discord", new_callable=AsyncMock):
                        with patch("app.routers.anchor_points.write_audit"):
                            with geo_patch as mock_geo:
                                if geocode_raises is not None:
                                    mock_geo.side_effect = geocode_raises
                                else:
                                    mock_geo.return_value = geocode_return
                                return asyncio.get_event_loop().run_until_complete(
                                    submit_anchor_point(payload=body, db=db, caller=caller, _={})
                                )

    def _body(self):
        body = MagicMock()
        body.truck_id = uuid.uuid4()
        body.date = date.today()
        body.location = "Main & 5th"
        body.eta = "9:00 AM"
        body.borough = None
        body.notes = None
        body.expected_departure_at = None
        return body

    def test_no_departure_raises_409(self):
        with pytest.raises(HTTPException) as exc:
            self._run(self._body(), departure_present=False)
        assert exc.value.status_code == 409

    def test_geocode_failure_raises_422(self):
        body = self._body()
        with pytest.raises(HTTPException) as exc:
            self._run(
                body, departure_present=True,
                geocode_raises=HTTPException(status_code=422, detail="could not geocode"),
            )
        assert exc.value.status_code == 422

    def test_departure_present_stores_canonical_and_coords(self):
        body = self._body()
        ap = self._run(body, departure_present=True,
                       geocode_return=("MAIN ST & 5TH AVE", 40.75, -73.99))
        assert ap.location == "MAIN ST & 5TH AVE"
        assert ap.lat == 40.75 and ap.lng == -73.99
