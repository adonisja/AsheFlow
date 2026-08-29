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


# ADR-322: `driver` moved OUT of this list — it is now one-per-truck too, with
# its own partial index. `driver_trainee` takes its place, which also pins the
# rule that a trainee riding with a driver is legal: if the driver predicate
# ever grew to include trainees, this parametrisation would fail.
@pytest.mark.parametrize("role", ["walker", "trainee", "trainer", "driver_trainee"])
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


def test_one_driver_per_truck(db):
    """ADR-322 D1 — the same guarantee as the captain slot, for the same reason.

    Lives beside the captain tests because the two indexes must stay symmetric:
    a change to one that is not made to the other is the kind of drift this file
    exists to catch.
    """
    import pytest
    from sqlalchemy.exc import IntegrityError

    assignment_id = uuid.uuid4()
    db.add(_member(assignment_id, "driver"))
    db.add(_member(assignment_id, "driver"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_driver_and_a_driver_trainee_share_a_truck(db):
    """THE pairing the predicate must not break (ADR-264): a trainee rides with
    their supervising driver. `driver_trainee` is a distinct role string, so
    this is legal by construction — the test pins that it stays so."""
    assignment_id = uuid.uuid4()
    db.add(_member(assignment_id, "driver"))
    db.add(_member(assignment_id, "driver_trainee"))
    db.commit()

    rows = db.query(AssignmentMember).filter(
        AssignmentMember.assignment_id == assignment_id,
    ).all()
    assert len(rows) == 2
