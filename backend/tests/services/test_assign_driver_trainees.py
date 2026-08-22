"""ADR-264 — placing driver trainees, and refusing to place them.

THE FAILURES THIS GUARDS AGAINST
--------------------------------
1. A trainee paired with a driver who has never supervised them — the system
   inventing a supervising relationship (operator, 2026-08-22).
2. A trainee placed on a truck while unpaired, which is one dispatch edit away
   from an unapproved pairing.
3. A trainee silently dropped when no supervisor is available. Held out is only
   safe if it is VISIBLE; without the warning it is indistinguishable from not
   being scheduled.
4. A solo trainee produced automatically. Solo is a dispatch approval (D7).
"""
import inspect

import pytest

from app.services import assign_driver_trainees as mod
from app.services.assign_driver_trainees import assign_driver_trainees

SRC = inspect.getsource(assign_driver_trainees)


class _Emp:
    def __init__(self, eid, name="T", role="driver", is_active=True):
        self.id, self.name, self.role, self.is_active = eid, name, role, is_active


class _DB:
    """Returns supervisor history rows, then placed-driver Employee rows."""

    def __init__(self, history=(), employees=()):
        self.history, self.employees = list(history), list(employees)
        self._mode = None

    def query(self, *cols):
        # driver_supervision queries TrainingRecord columns; this module
        # queries Employee. Distinguish by what was asked for.
        self._mode = "emp" if any(getattr(c, "class_", None) is not None
                                  and getattr(c, "key", "") == "id" for c in cols) else None
        first = cols[0] if cols else None
        self._mode = "emp" if getattr(first, "__name__", "") == "Employee" else "hist"
        return self

    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.employees if self._mode == "emp" else self.history


def _crews(driver_id=None):
    crew = [{"id": driver_id, "role": "driver"}] if driver_id else []
    return {"truck-1": crew}


class TestPairing:
    def test_a_prior_supervisor_on_a_truck_gets_the_trainee(self):
        crews = _crews("d1")
        db = _DB(history=[("d1", "2026-08-21")], employees=[_Emp("d1")])
        warnings = assign_driver_trainees(
            [_Emp("t1", name="Trainee")], crews, db,
            company_id="c1", target_date="2026-08-22",
        )
        assert warnings == []
        placed = [m for m in crews["truck-1"] if m["role"] == "driver_trainee"]
        assert len(placed) == 1
        assert placed[0]["paired_trainer_id"] == "d1"
        assert placed[0]["id"] == "t1"

    def test_the_trainee_lands_on_their_supervisors_truck(self):
        crews = {"truck-1": [{"id": "d9", "role": "driver"}],
                 "truck-2": [{"id": "d1", "role": "driver"}]}
        db = _DB(history=[("d1", "2026-08-21")], employees=[_Emp("d1"), _Emp("d9")])
        assign_driver_trainees([_Emp("t1")], crews, db,
                               company_id="c1", target_date="2026-08-22")
        assert any(m["role"] == "driver_trainee" for m in crews["truck-2"])
        assert not any(m["role"] == "driver_trainee" for m in crews["truck-1"])


class TestHeldOutNotPlaced:
    def test_first_day_is_not_placed(self):
        """No history — the system must not pick a driver, even with one right
        there."""
        crews = _crews("d1")
        db = _DB(history=[], employees=[_Emp("d1")])
        warnings = assign_driver_trainees([_Emp("t1", name="Newbie")], crews, db,
                                          company_id="c1", target_date="2026-08-22")
        assert not any(m["role"] == "driver_trainee" for m in crews["truck-1"])
        assert len(warnings) == 1
        assert warnings[0]["reason"] == "first_day"

    def test_no_prior_supervisor_on_dispatch_is_not_placed(self):
        crews = _crews("d9")
        db = _DB(history=[("d1", "2026-08-21")], employees=[_Emp("d9")])
        warnings = assign_driver_trainees([_Emp("t1")], crews, db,
                                          company_id="c1", target_date="2026-08-22")
        assert not any(m["role"] == "driver_trainee" for m in crews["truck-1"])
        assert warnings[0]["reason"] == "unavailable"

    def test_the_trainee_is_never_dropped_without_a_warning(self):
        """Held out is only safe if it is visible. A silent skip is
        indistinguishable from not being scheduled."""
        crews = _crews("d9")
        db = _DB(history=[], employees=[_Emp("d9")])
        warnings = assign_driver_trainees([_Emp("t1", name="Ghost")], crews, db,
                                          company_id="c1", target_date="2026-08-22")
        assert len(warnings) == 1
        assert "Ghost" in warnings[0]["message"]
        assert warnings[0]["employee_id"] == "t1"

    def test_the_message_names_the_two_ways_out(self):
        crews = _crews("d9")
        db = _DB(history=[], employees=[_Emp("d9")])
        w = assign_driver_trainees([_Emp("t1")], crews, db,
                                   company_id="c1", target_date="2026-08-22")[0]
        assert "Pair them with a driver" in w["message"]
        assert "solo" in w["message"]


class TestNeverSolo:
    def test_no_branch_places_a_trainee_without_a_supervisor(self):
        """The pass produces paired or unpaired-and-alerting, never solo."""
        # Ordering, not a fixed-size window: the guard sits ~2.4k chars before
        # the placement, and a magic offset would break on any edit between
        # them while proving nothing extra.
        i_guard = SRC.index("if supervisor_id is None:")
        i_place = SRC.index('"role": "driver_trainee",')
        assert i_guard < i_place, (
            "placement must be unreachable without a resolved supervisor"
        )
        assert "continue" in SRC[i_guard:i_place], "the guard must skip, not fall through"
        assert "paired_trainer_id" in SRC[i_place : i_place + 200]

    def test_it_never_calls_can_supervise_directly_to_pick(self):
        """Picking any eligible driver is the thing continuity forbids."""
        assert "eligible_supervisors(" not in SRC


class TestWarningShape:
    def test_every_emitted_warning_carries_a_type(self):
        """run_dispatch reshapes warnings: a dict with employee_id but NO type
        is rewritten as a ban_conflict, message and all. Asserting the string
        appears in SOURCE is not enough — there are two warning dicts here, and
        dropping the key from one left the other's literal in place. Assert on
        the emitted objects instead.

        Planted and confirmed: removing the key from the first dict passed the
        source-level check and fails this one."""
        crews = _crews("d9")
        db = _DB(history=[], employees=[_Emp("d9")])
        emitted = assign_driver_trainees([_Emp("t1")], crews, db,
                                         company_id="c1", target_date="2026-08-22")
        assert emitted, "expected an unpaired warning"
        for w in emitted:
            assert w.get("type") == "driver_trainee_unpaired", (
                f"warning without a type is rewritten as a ban_conflict: {w}"
            )
            assert "employee_id" in w

    def test_the_unavailable_warning_also_carries_a_type(self):
        """The second emission path — a different dict literal."""
        crews = _crews("d9")
        db = _DB(history=[("d1", "2026-08-21")], employees=[_Emp("d9")])
        emitted = assign_driver_trainees([_Emp("t1")], crews, db,
                                         company_id="c1", target_date="2026-08-22")
        assert [w["type"] for w in emitted] == ["driver_trainee_unpaired"]

    def test_the_reason_distinguishes_first_day_from_unavailable(self):
        """Same instruction to the caller, different sentence to the human."""
        assert '"reason": reason' in SRC
        assert "first supervised day" in SRC
        assert "none of the drivers who have supervised" in SRC


class TestDegenerateInputs:
    def test_no_trainees_returns_no_warnings(self):
        crews = _crews("d1")
        assert assign_driver_trainees([], crews, _DB(), company_id="c1",
                                      target_date="2026-08-22") == []

    def test_no_drivers_placed_means_everyone_is_held_out(self):
        crews = {"truck-1": []}
        db = _DB(history=[("d1", "2026-08-21")], employees=[])
        warnings = assign_driver_trainees([_Emp("t1")], crews, db,
                                          company_id="c1", target_date="2026-08-22")
        assert len(warnings) == 1
        assert crews["truck-1"] == []


class TestTenancy:
    def test_the_candidate_query_is_company_scoped(self):
        assert "Employee.company_id == company_id" in SRC
