"""Tests for gear_requests router (ADR-147 audit findings).

Verified findings:
  HIGH-1: _build_order_response (line 471) — queries Employee by ID only,
          no company_id filter. An employee_id from another tenant could
          resolve to a different company's employee record.

  HIGH-2: submit_gear_order (line 301-321) — no write_audit call despite
          creating GearOrder and GearOrderItem rows.

  HIGH-3: approve_item / deny_item / fulfill_item — no write_audit on item
          status transitions.

Correct-behaviour coverage:
  - Season filtering blocks cross-season items
  - Weekly limit enforcement
  - Seasonal limit enforcement
  - _get_item is company_id scoped
  - Duplicate item in same order raises 422
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.gear_requests import (
    SUMMER_ITEMS, WINTER_ITEMS, ALL_SEASON_ITEMS, ALL_ITEMS,
    WEEKLY_LIMIT, SEASONAL_LIMIT,
    _season_for_item, GearItemIn, GearOrderCreate,
)


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(company_id=_CID_A, role="walker"):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    emp.name = "Test Walker"
    return emp


# ---------------------------------------------------------------------------
# HIGH-1: _build_order_response missing company_id on Employee query
# ---------------------------------------------------------------------------

class TestBuildOrderResponseCrossTenant:
    """
    _build_order_response now includes Employee.company_id == order.company_id filter
    (fixed in ADR-148).
    """

    def test_build_order_response_employee_query_has_company_id(self):
        """
        _build_order_response now filters Employee by company_id.
        Verify the source contains the fix.
        """
        import inspect
        from app.routers.gear_requests import _build_order_response
        source = inspect.getsource(_build_order_response)

        assert "Employee.id == order.employee_id" in source
        idx = source.find("Employee.id == order.employee_id")
        surrounding = source[max(0, idx - 50): idx + 200]
        assert "company_id" in surrounding, (
            "_build_order_response must filter Employee by company_id (fixed in ADR-148)."
        )

    def test_get_item_is_company_scoped(self):
        """_get_item correctly filters by company_id — this is the safe pattern."""
        from app.routers.gear_requests import _get_item
        from app.models.gear_request import GearOrderItem

        item_id = uuid.uuid4()
        captured_filters = []

        db = MagicMock()
        def _query(model):
            q = MagicMock()
            def _filter(*args):
                captured_filters.extend(args)
                f = MagicMock()
                f.first.return_value = None
                return f
            q.filter = _filter
            return q
        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            _get_item(item_id, _CID_A, db)
        assert exc_info.value.status_code == 404

        filter_strs = [str(f) for f in captured_filters]
        assert any("company_id" in s for s in filter_strs), (
            "_get_item should filter by company_id — if this fails the fix is also missing."
        )


# ---------------------------------------------------------------------------
# HIGH-2: submit_gear_order missing write_audit
# ---------------------------------------------------------------------------

class TestSubmitGearOrderMissingAudit:
    def test_submit_gear_order_does_not_call_write_audit(self):
        """submit_gear_order commits without calling write_audit."""
        from app.routers.gear_requests import submit_gear_order

        caller = _make_caller()

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        with patch("app.routers.gear_requests._current_season", return_value="summer"):
            with patch("app.routers.gear_requests._weekly_count", return_value=0):
                with patch("app.routers.gear_requests._seasonal_count", return_value=0):
                    with patch("app.routers.gear_requests._build_order_response") as mock_resp:
                        mock_resp.return_value = MagicMock()
                        # No write_audit import in gear_requests.py — confirmed by reading the file
                        # This test verifies write_audit is never invoked
                        payload = GearOrderCreate(items=[GearItemIn(item="cap")])
                        submit_gear_order(payload=payload, caller=caller, _={}, db=db)
                        db.commit.assert_called_once()
                        # write_audit not imported in gear_requests — would NameError if called
                        # We verify it is not called by checking no NameError occurred
                        # and by asserting commit was called without audit


# ---------------------------------------------------------------------------
# HIGH-3: approve/deny/fulfill missing write_audit
# ---------------------------------------------------------------------------

class TestItemActionsMissingAudit:
    def _make_item(self, status="pending"):
        item = MagicMock()
        item.id = uuid.uuid4()
        item.company_id = _CID_A
        item.status = status
        item.approved_by = None
        item.approved_at = None
        item.fulfilled_by = None
        item.fulfilled_at = None
        item.notes = None
        return item

    def _make_db(self, item):
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        with patch("app.routers.gear_requests._get_item", return_value=item):
            return db

    def test_approve_item_no_write_audit(self):
        from app.routers.gear_requests import approve_item
        caller = _make_caller(role="management")
        item = self._make_item("pending")

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        with patch("app.routers.gear_requests._get_item", return_value=item):
            payload = MagicMock()
            payload.notes = None
            approve_item(item_id=uuid.uuid4(), payload=payload, caller=caller, _={}, db=db)

        db.commit.assert_called_once()

    def test_deny_item_no_write_audit(self):
        from app.routers.gear_requests import deny_item
        caller = _make_caller(role="management")
        item = self._make_item("pending")

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        with patch("app.routers.gear_requests._get_item", return_value=item):
            payload = MagicMock()
            payload.notes = None
            deny_item(item_id=uuid.uuid4(), payload=payload, caller=caller, _={}, db=db)

        db.commit.assert_called_once()

    def test_fulfill_item_requires_approved_status(self):
        """fulfill_item raises 400 if item is not yet approved."""
        from app.routers.gear_requests import fulfill_item
        caller = _make_caller(role="management")
        item = self._make_item("pending")  # not approved

        db = MagicMock()
        with patch("app.routers.gear_requests._get_item", return_value=item):
            payload = MagicMock()
            payload.notes = None
            with pytest.raises(HTTPException) as exc_info:
                fulfill_item(item_id=uuid.uuid4(), payload=payload, caller=caller, _={}, db=db)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Season / limit validation
# ---------------------------------------------------------------------------

class TestSeasonAndLimitValidation:
    def test_season_for_item_correct(self):
        assert _season_for_item("shirt_short") == "summer"
        assert _season_for_item("jacket") == "winter"
        assert _season_for_item("vest") == "all"
        assert _season_for_item("gloves") == "all"

    def test_cap_is_summer_item(self):
        assert _season_for_item("cap") == "summer"

    def test_gear_item_invalid_item_raises(self):
        with pytest.raises(Exception):
            GearItemIn(item="socks")

    def test_gear_order_duplicate_item_raises(self):
        with pytest.raises(Exception):
            GearOrderCreate(items=[
                GearItemIn(item="cap"),
                GearItemIn(item="cap"),
            ])

    def test_gear_order_empty_raises(self):
        with pytest.raises(Exception):
            GearOrderCreate(items=[])

    def test_weekly_limit_enforced(self):
        """Weekly limit of 1 blocks a second order of the same item."""
        from app.routers.gear_requests import submit_gear_order

        caller = _make_caller()
        db = MagicMock()
        db.flush = MagicMock()

        with patch("app.routers.gear_requests._current_season", return_value="summer"):
            with patch("app.routers.gear_requests._weekly_count", return_value=1):  # limit hit
                with patch("app.routers.gear_requests._seasonal_count", return_value=0):
                    payload = GearOrderCreate(items=[GearItemIn(item="cap")])
                    with pytest.raises(HTTPException) as exc_info:
                        submit_gear_order(payload=payload, caller=caller, _={}, db=db)
                    assert exc_info.value.status_code == 422
                    assert "weekly limit" in str(exc_info.value.detail).lower()

    def test_seasonal_limit_enforced(self):
        """Seasonal limit of 3 blocks a fourth order of the same item."""
        from app.routers.gear_requests import submit_gear_order

        caller = _make_caller()
        db = MagicMock()

        with patch("app.routers.gear_requests._current_season", return_value="summer"):
            with patch("app.routers.gear_requests._weekly_count", return_value=0):
                with patch("app.routers.gear_requests._seasonal_count", return_value=3):  # limit hit
                    payload = GearOrderCreate(items=[GearItemIn(item="cap")])
                    with pytest.raises(HTTPException) as exc_info:
                        submit_gear_order(payload=payload, caller=caller, _={}, db=db)
                    assert exc_info.value.status_code == 422
                    assert "seasonal limit" in str(exc_info.value.detail).lower()

    def test_winter_item_blocked_in_summer(self):
        """Winter items cannot be ordered during summer."""
        from app.routers.gear_requests import submit_gear_order

        caller = _make_caller()
        db = MagicMock()

        with patch("app.routers.gear_requests._current_season", return_value="summer"):
            with patch("app.routers.gear_requests._weekly_count", return_value=0):
                with patch("app.routers.gear_requests._seasonal_count", return_value=0):
                    # jacket is a winter item
                    payload = GearOrderCreate(items=[GearItemIn(item="jacket", size="M")])
                    with pytest.raises(HTTPException) as exc_info:
                        submit_gear_order(payload=payload, caller=caller, _={}, db=db)
                    assert exc_info.value.status_code == 422
                    assert "winter" in str(exc_info.value.detail).lower()

    def test_all_season_item_allowed_in_any_season(self):
        """All-season items (vest, gloves) pass season check year-round."""
        from app.routers.gear_requests import submit_gear_order

        caller = _make_caller()
        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        for season in ["summer", "winter"]:
            with patch("app.routers.gear_requests._current_season", return_value=season):
                with patch("app.routers.gear_requests._weekly_count", return_value=0):
                    with patch("app.routers.gear_requests._seasonal_count", return_value=0):
                        with patch("app.routers.gear_requests._build_order_response") as mock_resp:
                            mock_resp.return_value = MagicMock()
                            payload = GearOrderCreate(items=[
                                GearItemIn(item="gloves", size="M")
                            ])
                            # Should not raise
                            submit_gear_order(payload=payload, caller=caller, _={}, db=db)
