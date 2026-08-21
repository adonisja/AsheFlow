"""Check-in deadline config + NCNS ordering guards (ADR-228).

Public router (companies.py). Mock-DB tests for the add/delete guards:
  - NCNS cutoff must be set before any deadline is accepted.
  - Check-In #1 offset must be >= the NCNS cutoff.
  - each subsequent offset strictly greater than the previous.
  - only the last deadline may be deleted.
  - raising NCNS above an existing Check-In #1 is rejected.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers.companies import (
    add_check_in_deadline, delete_check_in_deadline, update_my_company_config,
    CheckInDeadlineCreate,
)
from app.models.company import CompanyConfig
from app.models.check_in_deadline import CheckInDeadline

_CID = uuid.uuid4()


def _caller():
    return SimpleNamespace(id=uuid.uuid4(), company_id=_CID, role="admin", name="Admin")


def _db(*, ncns, deadlines):
    """ncns=int|None on the config; deadlines=list of (sequence, offset)."""
    rows = [SimpleNamespace(id=uuid.uuid4(), company_id=_CID, sequence=s, offset_minutes=o)
            for s, o in deadlines]
    cfg = SimpleNamespace(company_id=_CID, ncns_cutoff_minutes=ncns, is_configured=True)
    db = MagicMock()

    def _query(model):
        q = MagicMock()
        def _filter(*a):
            f = MagicMock(); f.filter.return_value = f
            if model is CheckInDeadline:
                f.order_by.return_value = SimpleNamespace(all=lambda: sorted(rows, key=lambda r: r.sequence))
                # sequence==1 lookup (reverse guard)
                f.first.return_value = next((r for r in rows if r.sequence == 1), None)
            elif model is CompanyConfig:
                f.first.return_value = cfg
            else:
                f.first.return_value = None
            return f
        q.filter = _filter
        return q
    db.query = _query
    db.add = MagicMock(); db.delete = MagicMock(); db.commit = MagicMock(); db.refresh = MagicMock()
    return db


def _add(db, offset):
    return add_check_in_deadline(payload=CheckInDeadlineCreate(offset_minutes=offset),
                                 caller=_caller(), _={}, db=db)


def test_ncns_must_be_set_first():
    db = _db(ncns=None, deadlines=[])
    with pytest.raises(HTTPException) as exc:
        _add(db, 90)
    assert exc.value.status_code == 409
    assert "ncns cutoff" in str(exc.value.detail).lower()


def test_check_in_1_below_ncns_rejected():
    db = _db(ncns=60, deadlines=[])
    with pytest.raises(HTTPException) as exc:
        _add(db, 45)          # earlier than NCNS
    assert exc.value.status_code == 422
    assert "at or after the ncns cutoff" in str(exc.value.detail).lower()


def test_check_in_1_at_or_after_ncns_ok():
    db = _db(ncns=60, deadlines=[])
    row = _add(db, 60)         # exactly at NCNS is allowed
    assert row.sequence == 1 and row.offset_minutes == 60
    db.add.assert_called_once()


def test_subsequent_must_be_strictly_greater():
    db = _db(ncns=60, deadlines=[(1, 90)])
    with pytest.raises(HTTPException) as exc:
        _add(db, 90)           # equal to previous → reject
    assert exc.value.status_code == 422
    assert "must be later than" in str(exc.value.detail).lower()


def test_subsequent_greater_ok_and_appends_next_sequence():
    db = _db(ncns=60, deadlines=[(1, 90)])
    row = _add(db, 150)
    assert row.sequence == 2 and row.offset_minutes == 150


def test_only_last_deadline_deletable():
    db = _db(ncns=60, deadlines=[(1, 90), (2, 150)])
    with pytest.raises(HTTPException) as exc:
        delete_check_in_deadline(sequence=1, caller=_caller(), _={}, db=db)
    assert exc.value.status_code == 409


def test_delete_last_ok():
    db = _db(ncns=60, deadlines=[(1, 90), (2, 150)])
    out = delete_check_in_deadline(sequence=2, caller=_caller(), _={}, db=db)
    assert out["deleted_sequence"] == 2
    db.delete.assert_called_once()


def test_raising_ncns_above_check_in_1_rejected():
    db = _db(ncns=60, deadlines=[(1, 90)])
    payload = SimpleNamespace(model_dump=lambda **k: {"ncns_cutoff_minutes": 120})
    with pytest.raises(HTTPException) as exc:
        update_my_company_config(payload=payload, caller=_caller(), _={}, db=db)
    assert exc.value.status_code == 422
    assert "can't be later than" in str(exc.value.detail).lower()
