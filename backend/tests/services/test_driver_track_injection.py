"""ADR-264 phase 3 — driver curriculum injection.

THE FAILURES THIS GUARDS AGAINST
--------------------------------
1. A driver trainee handed WALKER material. ADR-263 scoped the curriculum by
   role precisely so this cannot happen; injection is where the scoping is
   applied or lost.
2. Observation landing anywhere but last (D3).
3. A solo day closing a phase — the trainee reaches observation never having
   been observed (D8, "the rule that protects the program").
4. A driver trainee silently skipped, which is how someone goes a whole program
   with no records and nobody finds out.
"""
import inspect

from app.services import training_injection as ti


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


DRIVER = _code_only(ti._inject_driver_track)
MODULE = _code_only(ti)


class TestTheTracksStaySeparate:
    def test_the_driver_pass_uses_driver_curriculum(self):
        """The whole point of ADR-263's roles array."""
        assert "TRACK_DRIVER in (i.roles or [])" in MODULE
        assert "TRACK_WALKER in (i.roles or [])" in MODULE

    def test_the_driver_list_is_what_gets_passed_to_the_driver_pass(self):
        """Both lists exist; the bug is passing the WRONG one. A planted
        `curriculum=curriculum` (the walker list) passed every other test in
        this file — the two lists are structurally identical, so only the
        argument name distinguishes them."""
        i = MODULE.index("_inject_driver_track(")
        call = MODULE[i : i + 400]
        assert "curriculum=driver_curriculum," in call, (
            "the driver pass must receive driver_curriculum — passing the "
            "walker list hands a driver trainee walker material"
        )
        assert "curriculum=curriculum," not in call

    def test_driver_trainees_are_collected_not_skipped(self):
        """They used to be counted and logged as unimplemented."""
        assert 'elif member["role"] == "driver_trainee":' in MODULE
        assert "driver_trainees_in_crews.append" in MODULE

    def test_the_old_skip_counter_is_gone(self):
        """Dead code after the track shipped (ADR-115 dim 5)."""
        assert "skipped_driver_trainees" not in MODULE
        assert "elif False" not in MODULE

    def test_the_driver_pass_is_separate_from_the_walker_loop(self):
        """Threading a track flag through the walker loop would put two
        programs in one control flow, where every future edit must be checked
        against both."""
        assert "_inject_driver_track(" in MODULE

    def test_walker_apparatus_is_absent_from_the_driver_pass(self):
        """Continuation requests and the phase-4 observation mirror are walker
        mechanics; a driver trainee has neither."""
        assert "TrainerContinuationRequest" not in DRIVER
        assert "mandatory_phases_1_3" not in DRIVER


class TestPhaseNumbersComeFromTheConfig:
    def test_the_plan_is_resolved_per_company(self):
        assert "phase_plan(cfg, TRACK_DRIVER)" in DRIVER

    def test_observation_and_quiz_are_derived_never_hardcoded(self):
        """D3 — with N=3 a hardcoded 5 is past the end of the program."""
        assert "plan.is_observation(current_phase)" in DRIVER
        assert "plan.is_quiz(current_phase)" in DRIVER
        assert "current_day_number == plan.observation" in DRIVER
        assert "== 4" not in DRIVER and "== 5" not in DRIVER

    def test_authored_phases_are_mapped_onto_slots(self):
        """D4 — merge when authored > slots, 1:1 when fewer. Never drop."""
        assert "compress_phase_map(authored, plan.teaching_slots)" in DRIVER


class TestSoloDays:
    def test_an_unpaired_trainee_still_gets_a_record(self):
        """D8 — a solo day is a REAL workday. Omitting the record makes a
        trainee who worked look absent, and hides why the program ran long."""
        assert "supervised=supervisor_id is not None" in DRIVER
        assert "driver_trainer_id=supervisor_id" in DRIVER

    def test_no_branch_skips_a_trainee_for_having_no_supervisor(self):
        """The tempting shortcut: `if supervisor_id is None: continue`. It
        reads as defensive and is the exact silent-drop D8 forbids — the
        trainee works the day and no record exists.

        Planted and confirmed: without this assertion the skip passes every
        other test here, because a skipped trainee leaves no trace to assert
        against."""
        loop = DRIVER[DRIVER.index("for trainee_id, supervisor_id in driver_trainees:"):]
        head = loop[: loop.index("record = TrainingRecord(")]
        assert "supervisor_id is None" not in head, (
            "a driver trainee without a supervisor must still get a record "
            "(supervised=False), never be skipped"
        )
        assert "continue" not in head.split("existing")[0]

    def test_an_unsupervised_record_cannot_close_a_phase(self):
        """THE rule (D8). Without it, solo days accumulate and the trainee
        reaches observation never having been observed."""
        from app.routers import training

        src = _code_only(training.update_task)
        assert "and record.supervised" in src

    def test_the_guard_is_on_the_auto_close_path(self):
        """The gate-open branch is where a completed day closes itself."""
        from app.routers import training

        src = _code_only(training.update_task)
        i = src.index("record.phase_closed = True")
        assert "record.supervised" in src[max(0, i - 200):i]


class TestPhaseAdvancement:
    def test_a_phase_that_did_not_close_carries_over(self):
        """ADR-046 — missed days cost nothing; the phase waits."""
        assert "current_phase = last.current_day_number" in DRIVER

    def test_a_closed_phase_advances_by_one(self):
        assert "current_phase = last.current_day_number + 1" in DRIVER

    def test_observation_closed_leads_to_the_quiz(self):
        assert "current_phase = plan.quiz" in DRIVER

    def test_a_finished_trainee_is_skipped_not_re_injected(self):
        assert "last.current_day_number >= plan.quiz and last.phase_closed" in DRIVER


class TestObservationPhase:
    def test_it_mirrors_mandatory_items_as_demonstrations(self):
        """The trainee performs, the supervising driver observes."""
        i = DRIVER.index("plan.is_observation(current_phase)")
        window = DRIVER[i : i + 700]
        assert 'record_type="demonstration"' in window
        assert "i.is_mandatory" in window


class TestEmptyStates:
    def test_an_empty_driver_curriculum_is_loud(self):
        """Dimension 5 — an empty phase that auto-closes as complete is a
        silent drop."""
        assert "NO driver curriculum" in inspect.getsource(ti._inject_driver_track)
        assert "logger.error" in DRIVER

    def test_no_driver_trainees_returns_early(self):
        assert "if not driver_trainees:" in DRIVER

    def test_an_empty_slot_injects_no_tasks_and_does_not_raise(self):
        """D4 addendum — a trailing slot with no authored items is a practice
        day. `by_slot.get(...)` with a default, never an index."""
        assert "by_slot.get(current_phase, [])" in DRIVER


class TestTenancy:
    def test_every_query_is_company_scoped(self):
        """ADR-115 dim 1."""
        # Three: the existing-record lookup, its task delete, and the
        # previous-records read. Each scoped.
        assert DRIVER.count("db.query(") == 3
        assert DRIVER.count("company_id == company_id") == 3

    def test_every_written_row_carries_the_company(self):
        assert DRIVER.count("company_id=company_id,") >= 4
