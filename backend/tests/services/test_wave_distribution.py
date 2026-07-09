"""Wave distribution (ADR-187) — pool wiring tests + GUIDED spec tests.

The skipped tests below are the SPEC for the guided implementation of
select_wave_routes (D2) and match_assignees (D3). Unskip each as you build;
done when all green. Proprietary import → CI skip guard.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

import pytest

try:
    from app.services.wave_distribution import (
        build_assignee_pool, select_wave_routes, match_assignees,
        build_block_urgency, Assignee, BlockUrgency,
    )
except ImportError:
    pytest.skip("proprietary wave_distribution not available (CI skip)", allow_module_level=True)


# ── minimal stand-ins (only the fields the service touches) ─────────────────

@dataclass
class _Emp:
    id: uuid.UUID
    name: str
    role: str
    injury_status: Optional[str] = None

@dataclass
class _Member:
    employee_id: uuid.UUID
    role: str
    paired_trainer_id: Optional[uuid.UUID] = None

@dataclass
class _Route:
    route_number: int
    effort_class: str = "standard"
    status: str = "unassigned"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    block_keys: list = field(default_factory=list)


def _crew(*specs):
    """specs: (name, role[, injury[, paired_trainer_name]])"""
    emps, members, by_name = [], [], {}
    for spec in specs:
        name, role = spec[0], spec[1]
        injury = spec[2] if len(spec) > 2 else None
        e = _Emp(uuid.uuid4(), name, role, injury)
        emps.append(e); by_name[name] = e
    for spec in specs:
        name, role = spec[0], spec[1]
        paired = spec[3] if len(spec) > 3 else None
        members.append(_Member(by_name[name].id, role,
                               by_name[paired].id if paired else None))
    return emps, members, by_name


# ── D1 pool (wiring — should pass NOW) ───────────────────────────────────────

class TestBuildAssigneePool:
    def test_driver_is_the_only_exemption(self):
        emps, members, _ = _crew(("D", "driver"), ("W", "walker"), ("T", "trainer"))
        pool, _ = build_assignee_pool(emps, members)
        names = {a.name for a in pool}
        assert "D" not in names and {"W", "T"} <= names

    def test_paired_trainer_trainee_is_one_unit(self):
        emps, members, by = _crew(
            ("Trainee", "trainee", None, "Trainer"), ("Trainer", "trainer"), ("W", "walker"),
        )
        pool, conflicts = build_assignee_pool(emps, members)
        pairs = [a for a in pool if a.kind == "pair"]
        assert len(pairs) == 1 and pairs[0].employee_id == by["Trainee"].id
        assert not any(a.kind == "trainer" and a.name == "Trainer" for a in pool)
        assert len(pool) == 2 and not conflicts   # pair + walker

    def test_pair_injured_if_either_member_is(self):
        emps, members, _ = _crew(
            ("Trainee", "trainee", None, "Trainer"), ("Trainer", "trainer", "wrist"),
        )
        pool, _ = build_assignee_pool(emps, members)
        assert pool[0].kind == "pair" and pool[0].injury_status == "wrist"

    def test_pairing_to_absent_trainer_degrades_to_solo(self):
        ghost = uuid.uuid4()
        emps = [_Emp(uuid.uuid4(), "Trainee", "trainee")]
        members = [_Member(emps[0].id, "trainee", ghost)]
        pool, conflicts = build_assignee_pool(emps, members)
        assert pool[0].kind == "trainee" and conflicts


# ── D2 select_wave_routes (GUIDED SPEC — unskip as you implement) ────────────

def _routes(*efforts):
    return [_Route(i + 1, e) for i, e in enumerate(efforts)]

def _at(hour, minute=0):
    """Cut-off at a fixed test day + time (deterministic — no wall clock)."""
    return datetime(2026, 7, 1, hour, minute)

_NOW = _at(8)   # injected clock: tests run 'at 8am'

def _pool(n_full, n_light=0):
    pool = [Assignee(uuid.uuid4(), f"W{i}", "walker") for i in range(n_full)]
    pool += [Assignee(uuid.uuid4(), f"L{i}", "walker", injury_status="knee") for i in range(n_light)]
    return pool


class TestSelectWaveRoutes:
    def test_one_route_per_assignee(self):
        selected, _ = select_wave_routes(_routes(*["standard"] * 10), _pool(4))
        assert len(selected) == 4

    def test_cold_start_is_hardest_first(self):
        # no urgency data → pure effort ordering: heavies go out first
        selected, _ = select_wave_routes(
            _routes("easy", "heavy", "standard", "heavy", "easy"), _pool(2))
        assert [r.effort_class for r in selected] == ["heavy", "heavy"]

    def test_light_duty_claims_easiest_first(self):
        # 1 light-duty walker: the easiest non-heavy route is reserved for them
        # ahead of the hardest-first fill
        selected, _ = select_wave_routes(
            _routes("heavy", "easy", "standard", "heavy"), _pool(2, n_light=1))
        assert selected[0].effort_class == "easy"          # light-duty slot leads
        assert {r.effort_class for r in selected[1:]} == {"heavy"}

    def test_conflict_when_no_light_route_for_injured(self):
        _, conflicts = select_wave_routes(_routes("heavy", "heavy"), _pool(1, n_light=1))
        assert conflicts

    # ── banded urgency ranking (GUIDED D2) ──────────────────────────────────
    # Band 2: any block with a time cut-off — earliest cut-off first.
    # Band 1: no cut-off but difficulty-hard blocks — hard proportion desc.
    # Band 0: everything else — effort hardest-first (today's cold start).
    # The soft signal (band 1) must NEVER outrank a real cut-off (band 2).

    def test_earlier_cutoff_ranks_first(self):
        r_2pm = _Route(1, "standard", block_keys=["a"])
        r_9am = _Route(2, "standard", block_keys=["b"])
        urgency = {"a": BlockUrgency(cutoff_at=_at(14)), "b": BlockUrgency(cutoff_at=_at(9))}
        selected, _ = select_wave_routes(
            [r_2pm, r_9am], _pool(2), block_urgency=urgency, now=_NOW)
        assert [r.route_number for r in selected] == [2, 1]

    def test_cutoff_route_outranks_all_hard_blocks(self):
        # An easy route with a real 4pm cut-off beats a heavy route that is
        # 100% hard blocks but has no time limit — the soft signal is soft.
        r_hard = _Route(1, "heavy", block_keys=["h1", "h2", "h3"])
        r_cut = _Route(2, "easy", block_keys=["c1"])
        urgency = {"h1": BlockUrgency(is_hard=True), "h2": BlockUrgency(is_hard=True),
                   "h3": BlockUrgency(is_hard=True), "c1": BlockUrgency(cutoff_at=_at(16))}
        selected, _ = select_wave_routes(
            [r_hard, r_cut], _pool(1), block_urgency=urgency, now=_NOW)
        assert selected[0].route_number == 2

    def test_hard_proportion_orders_no_cutoff_routes(self):
        # No cut-offs anywhere: 4/5 hard blocks outranks 1/5 hard blocks.
        r_mostly = _Route(1, "standard", block_keys=["a", "b", "c", "d", "e"])
        r_barely = _Route(2, "standard", block_keys=["v", "w", "x", "y", "z"])
        urgency = {k: BlockUrgency(is_hard=True) for k in ("a", "b", "c", "d", "v")}
        selected, _ = select_wave_routes(
            [r_barely, r_mostly], _pool(2), block_urgency=urgency, now=_NOW)
        assert [r.route_number for r in selected] == [1, 2]

    def test_break_in_progress_shifts_priority_to_reopen(self):
        # 12:00–12:30 break already started (now 12:10): the ranking time
        # becomes the 12:30 reopen, so the 12:15 closing route goes out first;
        # a conflict surfaces the break window.
        r_break = _Route(1, "standard", block_keys=["a"])
        r_close = _Route(2, "standard", block_keys=["b"])
        urgency = {
            "a": BlockUrgency(cutoff_at=_at(12), cutoff_kind="break", resumes_at=_at(12, 30)),
            "b": BlockUrgency(cutoff_at=_at(12, 15), cutoff_kind="closing"),
        }
        selected, conflicts = select_wave_routes(
            [r_break, r_close], _pool(2), block_urgency=urgency, now=_at(12, 10))
        assert [r.route_number for r in selected] == [2, 1]
        assert any("12:30" in c for c in conflicts)   # break window surfaced

    def test_overdue_closing_stays_first_and_flags_call(self):
        # Closed at 9:00, now 9:40 — still ranks first (priority kept), and the
        # conflict says how overdue it is + instructs to call the customer.
        r_over = _Route(1, "standard", block_keys=["a"])
        r_later = _Route(2, "standard", block_keys=["b"])
        urgency = {"a": BlockUrgency(cutoff_at=_at(9)),
                   "b": BlockUrgency(cutoff_at=_at(14))}
        selected, conflicts = select_wave_routes(
            [r_over, r_later], _pool(2), block_urgency=urgency, now=_at(9, 40))
        assert selected[0].route_number == 1
        joined = " ".join(conflicts).lower()
        assert "call" in joined and "40" in joined

    def test_light_duty_takes_urgent_non_heavy_route(self):
        # Urgency outranks easiness inside the light-duty reservation too: the
        # standard route closing at 1pm goes to the light-duty walker, not the
        # no-pressure easy route. Heavy stays off-limits regardless.
        r_easy = _Route(1, "easy", block_keys=["a"])
        r_cut = _Route(2, "standard", block_keys=["b"])
        r_heavy = _Route(3, "heavy", block_keys=["c"])
        urgency = {"b": BlockUrgency(cutoff_at=_at(13))}
        selected, _ = select_wave_routes(
            [r_easy, r_cut, r_heavy], _pool(1, n_light=1), block_urgency=urgency, now=_NOW)
        assert selected[0].route_number == 2   # light-duty slot leads the selection

    def test_hard_proportion_breaks_cutoff_ties(self):
        # Same earliest cut-off → the route with more hard blocks goes first.
        r_soft = _Route(1, "standard", block_keys=["a", "b"])
        r_hard = _Route(2, "standard", block_keys=["c", "d"])
        urgency = {"a": BlockUrgency(cutoff_at=_at(14)),
                   "c": BlockUrgency(cutoff_at=_at(14)),
                   "d": BlockUrgency(is_hard=True)}
        selected, _ = select_wave_routes(
            [r_soft, r_hard], _pool(2), block_urgency=urgency, now=_NOW)
        assert [r.route_number for r in selected] == [2, 1]


# ── D3 match_assignees (GUIDED SPEC — unskip as you implement) ───────────────

class TestMatchAssignees:
    def test_every_selected_route_gets_an_assignee(self):
        routes = _routes("standard", "standard", "standard")
        pool = _pool(3)
        pairs, _ = match_assignees(routes, pool)
        assert len(pairs) == 3
        assert len({a.employee_id for _, a in pairs}) == 3   # no double assignment

    def test_light_duty_gets_leading_easy_routes(self):
        routes = _routes("easy", "heavy")
        pool = _pool(1, n_light=1)
        pairs, _ = match_assignees(routes, pool)
        by_route = {r.route_number: a for r, a in pairs}
        assert by_route[1].injury_status is not None       # easy → injured walker

    def test_recent_blocks_reduce_repeat_probability(self):
        # A walker who worked route blocks recently should draw them LESS often
        # than chance across many trials (rotation spreads familiarity as
        # call-out resilience). With W_REPEAT=0.6, full overlap gives weight
        # 0.4 vs 1.0 → P(repeat) ≈ 0.286; chance is 0.5. Seeded rng.
        import random
        rng = random.Random(1234)
        r_seen = _Route(1, "standard", block_keys=["a", "b"])
        r_new = _Route(2, "standard", block_keys=["c", "d"])
        x, y = _pool(2)
        recent = {x.employee_id: {"a", "b"}}

        hits = 0
        for _ in range(400):
            pairs, _ = match_assignees([r_seen, r_new], [x, y],
                                       recent_blocks=recent, rng=rng)
            by_route = {r.route_number: a for r, a in pairs}
            if by_route[1].employee_id == x.employee_id:
                hits += 1
        assert hits < 160   # well below the 200 expected by chance

    def test_heavy_wave1_biases_lighter_wave2(self):
        # An assignee whose completed day-effort is high should draw the heavy
        # route less often this wave. day_effort at the cap + heavy route →
        # weight 0.4 vs 1.0 → P ≈ 0.286; chance is 0.5. Seeded rng.
        import random
        rng = random.Random(1234)
        r_heavy = _Route(1, "heavy")
        r_easy = _Route(2, "easy")
        x, y = _pool(2)
        effort = {x.employee_id: 9.0}   # X already did ~3 standard routes

        hits = 0
        for _ in range(400):
            pairs, _ = match_assignees([r_heavy, r_easy], [x, y],
                                       day_effort=effort, rng=rng)
            by_route = {r.route_number: a for r, a in pairs}
            if by_route[1].employee_id == x.employee_id:
                hits += 1
        assert hits < 160   # loaded walker dodges the heavy well below chance

    def test_sitout_priority_to_most_completed(self):
        # D5: routes run short → staff with the FEWEST completed routes work
        # first; the 3-completed walker earns the sit-out.
        import random
        rng = random.Random(1234)
        routes = [_Route(1, "standard")]
        x, y = _pool(2)
        counts = {x.employee_id: 3, y.employee_id: 1}
        pairs, _ = match_assignees(routes, [x, y], completed_counts=counts, rng=rng)
        assert len(pairs) == 1 and pairs[0][1].employee_id == y.employee_id

# ── build_block_urgency — BuildingProfile rows → per-block facts ─────────────

@dataclass
class _Profile:
    block_key: str
    workload_class: str = "standard"
    closes_at: Optional[time] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None


class TestBuildBlockUrgency:
    DAY = date(2026, 7, 1)

    def test_earliest_event_wins_the_block(self):
        # Two buildings on one block: the 11:00 closing beats the 15:00 one.
        rows = [_Profile("b1", closes_at=time(15)), _Profile("b1", closes_at=time(11))]
        bu = build_block_urgency(rows, self.DAY, now=datetime(2026, 7, 1, 8))
        assert bu["b1"].cutoff_at == datetime(2026, 7, 1, 11)
        assert bu["b1"].cutoff_kind == "closing"

    def test_finished_break_yields_to_later_closing(self):
        # Break 12:00–12:30 is over at 13:00 — the 17:00 closing must surface
        # instead of the block dropping out of band 2 entirely.
        rows = [_Profile("b1", closes_at=time(17),
                         break_start=time(12), break_end=time(12, 30))]
        bu = build_block_urgency(rows, self.DAY, now=datetime(2026, 7, 1, 13))
        assert bu["b1"].cutoff_at == datetime(2026, 7, 1, 17)
        assert bu["b1"].cutoff_kind == "closing"

    def test_upcoming_break_beats_later_closing(self):
        rows = [_Profile("b1", closes_at=time(17),
                         break_start=time(12), break_end=time(12, 30))]
        bu = build_block_urgency(rows, self.DAY, now=datetime(2026, 7, 1, 8))
        assert bu["b1"].cutoff_kind == "break"
        assert bu["b1"].resumes_at == datetime(2026, 7, 1, 12, 30)

    def test_any_hard_building_marks_the_block(self):
        rows = [_Profile("b1", workload_class="standard"),
                _Profile("b1", workload_class="high_wait")]
        bu = build_block_urgency(rows, self.DAY, now=None)
        assert bu["b1"].is_hard
