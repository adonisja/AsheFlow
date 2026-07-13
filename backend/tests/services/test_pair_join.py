"""Tests for the shared D2 late-trainee join (ADR-199).

pair_join is public (no proprietary imports) — used by both arrival_confirm and
the Phase B dispatch reassignment. Covers route-lookup priority, the stamp, and
the 404/409 error contract.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.pair_join import find_trainer_route, join_trainee_to_route
from app.schemas.walker_routes import EFFORT_CAPACITY_PAIRED

_TRAINER = uuid.uuid4()
_TRAINEE = uuid.uuid4()
_OTHER = uuid.uuid4()


def _route(assigned_to, paired_trainee_id=None, effort_class="standard", capacity_limit_paired=None):
    return SimpleNamespace(
        assigned_to=assigned_to,
        paired_trainee_id=paired_trainee_id,
        effort_class=effort_class,
        capacity_limit_paired=capacity_limit_paired,
    )


class TestFindTrainerRoute:
    def test_prefers_route_already_carrying_trainee(self):
        seeded = _route(_TRAINER, paired_trainee_id=_TRAINEE)
        unpaired = _route(_TRAINER, paired_trainee_id=None)
        assert find_trainer_route([unpaired, seeded], _TRAINER, _TRAINEE) is seeded

    def test_falls_back_to_trainers_unpaired_route(self):
        unpaired = _route(_TRAINER, paired_trainee_id=None)
        assert find_trainer_route([unpaired], _TRAINER, _TRAINEE) is unpaired

    def test_none_when_trainer_has_no_route(self):
        other = _route(_OTHER, paired_trainee_id=None)
        assert find_trainer_route([other], _TRAINER, _TRAINEE) is None

    def test_skips_trainer_route_paired_to_different_trainee(self):
        # Trainer's only route already carries a DIFFERENT trainee → not eligible.
        taken = _route(_TRAINER, paired_trainee_id=_OTHER)
        assert find_trainer_route([taken], _TRAINER, _TRAINEE) is None


class TestJoinTraineeToRoute:
    def test_stamps_pairing_and_capacity(self):
        r = _route(_TRAINER, paired_trainee_id=None, effort_class="standard")
        route, cap = join_trainee_to_route([r], _TRAINER, _TRAINEE)
        assert route is r
        assert r.paired_trainee_id == _TRAINEE
        assert cap == EFFORT_CAPACITY_PAIRED["standard"]
        assert r.capacity_limit_paired == cap

    def test_uses_effort_class_capacity(self):
        cls = next(k for k in EFFORT_CAPACITY_PAIRED if k != "standard")
        r = _route(_TRAINER, effort_class=cls)
        _route_out, cap = join_trainee_to_route([r], _TRAINER, _TRAINEE)
        assert cap == EFFORT_CAPACITY_PAIRED[cls]

    def test_404_when_no_route(self):
        with pytest.raises(HTTPException) as exc:
            join_trainee_to_route([_route(_OTHER)], _TRAINER, _TRAINEE)
        assert exc.value.status_code == 404

    def test_409_when_already_confirmed(self):
        r = _route(_TRAINER, paired_trainee_id=_TRAINEE, capacity_limit_paired=18)
        with pytest.raises(HTTPException) as exc:
            join_trainee_to_route([r], _TRAINER, _TRAINEE)
        assert exc.value.status_code == 409
