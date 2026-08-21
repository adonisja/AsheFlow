"""ADR-256 D2 — exactly one captain slot per truck.

The invariant has two halves, and a broken index can satisfy one while failing the
other. Both are pinned here:

  1. a second captain on the same assignment is REJECTED
  2. every other role stays multi-row — a truck has many walkers

Half 2 exists because of how this bug actually shipped: `postgresql_where` alone is
silently dropped by SQLite, turning the partial index into a plain unique index on
assignment_id. The invariant "one captain per truck" still looked satisfied, while
ordinary driver and trainer inserts began failing. A test asserting only half 1
would have passed against the broken index.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.assignment_member import AssignmentMember
from tests.conftest import SEED_COMPANY_ID


def _member(assignment_id, role, employee_id=None):
    return AssignmentMember(
        id=uuid.uuid4(),
        company_id=SEED_COMPANY_ID,
        assignment_id=assignment_id,
        employee_id=employee_id or uuid.uuid4(),
        role=role,
    )


def test_second_captain_on_same_truck_is_rejected(db):
    assignment_id = uuid.uuid4()
    db.add(_member(assignment_id, "captain"))
    db.commit()

    db.add(_member(assignment_id, "captain"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_captain_slots_are_unique_per_truck_not_globally(db):
    """Two trucks may each have their own captain."""
    truck_a, truck_b = uuid.uuid4(), uuid.uuid4()
    db.add(_member(truck_a, "captain"))
    db.add(_member(truck_b, "captain"))
    db.commit()

    captains = db.query(AssignmentMember).filter(
        AssignmentMember.role == "captain",
    ).all()
    assert len(captains) == 2


@pytest.mark.parametrize("role", ["walker", "trainee", "trainer", "driver"])
def test_non_captain_roles_are_not_constrained(db, role):
    """The partial predicate must not degrade into a plain unique index.

    This is the half that caught the real bug: with `postgresql_where` only, SQLite
    dropped the predicate and this insert raised IntegrityError.
    """
    assignment_id = uuid.uuid4()
    db.add(_member(assignment_id, role))
    db.add(_member(assignment_id, role))
    db.commit()

    rows = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_id,
    ).all()
    assert len(rows) == 2


def test_a_full_crew_coexists_with_one_captain(db):
    """The realistic shape: one captain, one driver, several walkers."""
    assignment_id = uuid.uuid4()
    db.add(_member(assignment_id, "captain"))
    db.add(_member(assignment_id, "driver"))
    for _ in range(3):
        db.add(_member(assignment_id, "walker"))
    db.commit()

    rows = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_id,
    ).all()
    assert len(rows) == 5
    assert sum(1 for r in rows if r.role == "captain") == 1
