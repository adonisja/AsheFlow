"""ADR-264 D3/D4/D11 — phase arithmetic.

THE FAILURES THIS GUARDS AGAINST
--------------------------------
1. Observation landing anywhere but last. D3: "derived as phase == N, never
   hardcoded to 5" — with N=3 a hardcoded 5 is past the end of the program, and
   a hardcoded 4 puts observation in the middle.
2. A curriculum item silently dropped when the program is compressed. A dropped
   DVIC item is a safety gap, not a shorter course.
3. A bad config value taking dispatch down.
"""
import pytest

from app.services.training_phases import (
    MAX_PHASES, MIN_PHASES, TRACK_DRIVER, TRACK_WALKER,
    compress_phase_map, phase_plan, track_for_role,
)


class TestObservationIsAlwaysLast:
    @pytest.mark.parametrize("n", [2, 3, 4, 5, 8, 30])
    def test_observation_equals_n(self, n):
        p = phase_plan({"driver_training_days": n}, TRACK_DRIVER)
        assert p.observation == n
        assert p.is_observation(n)
        assert not p.is_observation(n - 1)

    def test_quiz_and_remediation_follow_observation(self):
        p = phase_plan({"driver_training_days": 5}, TRACK_DRIVER)
        assert (p.observation, p.quiz, p.remediation) == (5, 6, 7)

    def test_a_short_program_does_not_put_observation_in_the_middle(self):
        """The exact failure D3 names."""
        p = phase_plan({"driver_training_days": 3}, TRACK_DRIVER)
        assert p.observation == 3
        assert p.teaching_slots == 2


class TestConfigResolution:
    def test_each_track_reads_its_own_key(self):
        cfg = {"max_training_phase": 4, "driver_training_days": 6}
        assert phase_plan(cfg, TRACK_WALKER).total == 4
        assert phase_plan(cfg, TRACK_DRIVER).total == 6

    def test_missing_config_falls_back_per_track(self):
        assert phase_plan({}, TRACK_WALKER).total == 4
        assert phase_plan({}, TRACK_DRIVER).total == 5
        assert phase_plan(None, TRACK_DRIVER).total == 5

    @pytest.mark.parametrize("bad,expected", [(0, MIN_PHASES), (1, MIN_PHASES), (999, MAX_PHASES)])
    def test_a_bad_value_is_clamped_not_raised(self, bad, expected):
        """A misconfigured tenant must not take dispatch down; a clamped
        program is still coherent."""
        assert phase_plan({"driver_training_days": bad}, TRACK_DRIVER).total == expected


class TestTrackForRole:
    def test_the_two_entry_tracks(self):
        assert track_for_role("trainee") == TRACK_WALKER
        assert track_for_role("driver_trainee") == TRACK_DRIVER

    @pytest.mark.parametrize("role", ["driver", "walker", "trainer", "captain", "admin"])
    def test_everyone_else_trains_in_neither(self, role):
        """D2 — parallel entry tracks, not a career ladder. A `driver` is not in
        training; only a `driver_trainee` is."""
        assert track_for_role(role) is None


class TestCompressionNeverDropsAnItem:
    @pytest.mark.parametrize("authored,slots", [
        ([1, 2, 3], 4), ([1, 2, 3], 3), ([1, 2, 3], 2), ([1, 2, 3], 1),
        ([1, 2, 3, 4], 2), ([1, 2, 3, 4, 5, 6], 3), ([0, 1, 2, 3], 2),
    ])
    def test_every_authored_phase_lands_somewhere(self, authored, slots):
        m = compress_phase_map(authored, slots)
        assert set(m) == set(authored), "an authored phase was dropped"
        assert all(1 <= s <= slots for s in m.values())

    def test_curriculum_order_is_preserved(self):
        """Merging may combine phases but must never reorder them — safety
        content is authored in a deliberate sequence."""
        m = compress_phase_map([1, 2, 3, 4, 5, 6], 3)
        slots = [m[p] for p in sorted(m)]
        assert slots == sorted(slots)

    def test_the_adr_worked_example(self):
        """N=3 -> [1 orient+safety][2 custody][3 OBSERVE], from D4."""
        assert compress_phase_map([1, 2, 3], 2) == {1: 1, 2: 1, 3: 2}

    def test_merged_phases_land_early(self):
        """The run-up to observation should be lighter, not heavier."""
        m = compress_phase_map([1, 2, 3], 2)
        from collections import Counter
        per_slot = Counter(m.values())
        assert per_slot[1] >= per_slot[2]


class TestExpansion:
    def test_fewer_authored_than_slots_maps_one_to_one(self):
        """D4 addendum. The real case: 3 authored driver phases, N=5."""
        assert compress_phase_map([1, 2, 3], 4) == {1: 1, 2: 2, 3: 3}

    def test_the_trailing_slot_is_simply_absent(self):
        """Slot 4 carries no material — a practice day, not an error. Nothing
        raises and no phase is invented."""
        m = compress_phase_map([1, 2, 3], 4)
        assert 4 not in m.values()

    def test_authored_numbers_are_positional_not_literal(self):
        """A curriculum authored as [2,4,7] maps like [1,2,3]."""
        assert compress_phase_map([2, 4, 7], 3) == {2: 1, 4: 2, 7: 3}


class TestDegenerateInputs:
    def test_no_curriculum_is_empty_not_an_error(self):
        assert compress_phase_map([], 4) == {}

    def test_zero_slots_is_empty_not_a_crash(self):
        assert compress_phase_map([1, 2], 0) == {}
