"""ADR-520: the two most serious NameErrors, exercised.

Dispatch notification expiry (every dispatch publish, manual assignment, swap and
hub publish) and stop ownership (every walker start/complete/suggest/reconcile).
"""
from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import dispatch as D
from app.routers import rts as R
from tests.conftest import SEED_COMPANY_ID, make_employee


def test_dispatch_notification_expiry_runs_for_both_types(db):
    cfg = SimpleNamespace(dispatch_confirmation_cutoff=time(23, 59))
    future = date(2099, 1, 1)
    a = D._notification_expires_at("dispatch_assignment", future, cfg, db=db, company_id=SEED_COMPANY_ID)
    i = D._notification_expires_at("dispatch_assignment_info", future, cfg, db=db, company_id=SEED_COMPANY_ID)
    assert isinstance(a, datetime) and isinstance(i, datetime)
    assert a <= i, "the confirmation cutoff falls inside the day the info expires at"
    assert D._notification_expires_at("other_type", future, cfg, db=db, company_id=SEED_COMPANY_ID) is None


def test_stop_ownership_runs_and_still_refuses_a_stranger(db):
    walker = make_employee(db, role="walker", name="Owner Walker")
    stranger = make_employee(db, role="walker", name="Other Walker")
    db.commit()
    route = SimpleNamespace(executor_id=walker.id, phase4_solo_opted_in=False, truck_id=None,
                            assignment_id=None, date=date(2026, 10, 15), company_id=SEED_COMPANY_ID)
    R._assert_stop_ownership(walker, route, db)          # the owner: no error at all
    with pytest.raises(HTTPException) as e:
        R._assert_stop_ownership(stranger, route, db)
    assert e.value.status_code == 403
