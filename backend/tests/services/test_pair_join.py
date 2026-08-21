"""Tests for the shared D2 late-trainee join (ADR-199, reworked for ADR-212).

pair_join is public (no proprietary imports) — used by both arrival_confirm and
the Phase B dispatch reassignment. ADR-212: the paired route is the TRAINEE's
(executor) route; the join attaches the trainer as a supervisor participant.
Covers route-lookup by executor, the participant + capacity stamp, and the
404/409 error contract.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.pair_join import find_executor_route, join_trainee_to_route
from app.schemas.walker_routes import EFFORT_CAPACITY_PAIRED

_TRAINER = uuid.uuid4()
_TRAINEE = uuid.uuid4()
_OTHER = uuid.uuid4()
_CID = uuid.uuid4()


def _participant(role, employee_id):
    return SimpleNamespace(role=role, employee_id=employee_id)


def _route(executor_id=None, supervisor_ids=(), effort_class="standard", capacity_limit_paired=None):
    parts = []
    if executor_id is not None:
        parts.append(_participant("executor", executor_id))
    for sid in supervisor_ids:
        parts.append(_participant("supervisor", sid))
    return SimpleNamespace(
        participants=parts,
        effort_class=effort_class,
        capacity_limit_paired=capacity_limit_paired,
    )


class TestFindExecutorRoute:
    def test_finds_route_the_trainee_executes(self):
        trainee_route = _route(executor_id=_TRAINEE)
        other = _route(executor_id=_OTHER)
        assert find_executor_route([other, trainee_route], _TRAINEE) is trainee_route

    def test_none_when_trainee_has_no_route(self):
        assert find_executor_route([_route(executor_id=_OTHER)], _TRAINEE) is None

    def test_ignores_route_where_trainee_is_only_supervisor(self):
        # A route the trainee merely supervises is not "their executor route".
        supervised = _route(executor_id=_OTHER, supervisor_ids=[_TRAINEE])
        assert find_executor_route([supervised], _TRAINEE) is None


class TestJoinTraineeToRoute:
    def test_attaches_supervisor_and_capacity(self):
        r = _route(executor_id=_TRAINEE, effort_class="standard")
        route, cap = join_trainee_to_route([r], _TRAINER, _TRAINEE, _CID)
        assert route is r
        # trainer is now a supervisor participant on the trainee's route
        assert any(p.role == "supervisor" and p.employee_id == _TRAINER for p in r.participants)
        assert cap == EFFORT_CAPACITY_PAIRED["standard"]
        assert r.capacity_limit_paired == cap

    def test_uses_effort_class_capacity(self):
        cls = next(k for k in EFFORT_CAPACITY_PAIRED if k != "standard")
        r = _route(executor_id=_TRAINEE, effort_class=cls)
        _route_out, cap = join_trainee_to_route([r], _TRAINER, _TRAINEE, _CID)
        assert cap == EFFORT_CAPACITY_PAIRED[cls]

    def test_idempotent_supervisor_not_duplicated(self):
        r = _route(executor_id=_TRAINEE, supervisor_ids=[_TRAINER])
        # capacity not yet set, so the join proceeds; the trainer is already a
        # supervisor and must not be appended twice.
        join_trainee_to_route([r], _TRAINER, _TRAINEE, _CID)
        supervisors = [p for p in r.participants if p.role == "supervisor" and p.employee_id == _TRAINER]
        assert len(supervisors) == 1

    def test_404_when_no_route(self):
        with pytest.raises(HTTPException) as exc:
            join_trainee_to_route([_route(executor_id=_OTHER)], _TRAINER, _TRAINEE, _CID)
        assert exc.value.status_code == 404

    def test_409_when_already_confirmed(self):
        r = _route(executor_id=_TRAINEE, supervisor_ids=[_TRAINER], capacity_limit_paired=18)
        with pytest.raises(HTTPException) as exc:
            join_trainee_to_route([r], _TRAINER, _TRAINEE, _CID)
        assert exc.value.status_code == 409
