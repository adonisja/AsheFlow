"""ADR-264 D3/D4/D11 — phase arithmetic for both training tracks.

WHY THIS EXISTS
---------------
`training_injection.py` hardcoded `MAX_CURRICULUM_PHASE = 4` while
`CompanyConfig.max_training_phase` (default 4) sat in the config, exposed
through the companies API, defaulted in PLATFORM_DEFAULTS — and read by nobody.
The walker path ignored its own config value, and the literals 5 and 6 appeared
inline as "quiz day" and "remediation".

ADR-264 needs a configurable phase count for the driver track. Adding a second
config-driven count beside an ignored one would leave two ways to answer the
same question, so the fix is to make BOTH tracks read their config through here
(D11, "related debt to fix in the same change").

THE SHAPE OF A PROGRAM
----------------------
    phases 1..N-1   teaching
    phase  N        OBSERVATION      <- always last (D3)
    phase  N+1      quiz day
    phase  N+2      remediation (only after a failed quiz)

N is `max_training_phase` for walkers and `driver_training_days` for drivers.
Observation is derived as `phase == N`, **never hardcoded** — with N=3 a
hardcoded 5 would put observation past the end of the program, and a hardcoded 4
would put it in the middle.
"""
from dataclasses import dataclass

# Track identifiers. These match the values stored in TrainingCurriculum.roles
# and GraduationQuizTemplate.roles (ADR-263, ADR-264 D10), so a track is also
# the curriculum filter — one concept, one spelling.
TRACK_WALKER = "walker"
TRACK_DRIVER = "driver"

# The employee role that enters each track. `trainee` -> walker, `driver_trainee`
# -> driver. Two parallel entry tracks, not a career ladder (D2).
TRACK_BY_ROLE = {
    "trainee": TRACK_WALKER,
    "driver_trainee": TRACK_DRIVER,
}

_CONFIG_KEY = {
    TRACK_WALKER: "max_training_phase",
    TRACK_DRIVER: "driver_training_days",
}

# Floor of 2: one teaching phase plus the observation phase is the minimum
# coherent program (D11). A 1-phase program would be observation-only, with
# nothing taught before it.
MIN_PHASES = 2
MAX_PHASES = 30


@dataclass(frozen=True)
class PhasePlan:
    """The phase numbers for one track at one company."""
    track: str
    total: int          # N — the last TEACHING+OBSERVATION phase

    @property
    def observation(self) -> int:
        """Always the last phase (D3), never a hardcoded number."""
        return self.total

    @property
    def quiz(self) -> int:
        return self.total + 1

    @property
    def remediation(self) -> int:
        return self.total + 2

    @property
    def teaching_slots(self) -> int:
        """How many phases carry curriculum. Observation carries none."""
        return self.total - 1

    def is_observation(self, phase: int) -> bool:
        return phase == self.observation

    def is_quiz(self, phase: int) -> bool:
        return phase == self.quiz


def track_for_role(role: str) -> str | None:
    """Which training track a role belongs to, or None if it trains in neither."""
    return TRACK_BY_ROLE.get(role)


def phase_plan(config, track: str) -> PhasePlan:
    """Resolve a company's phase plan for one track.

    `config` is the resolved CompanyConfig dict (get_company_config), so the
    PLATFORM_DEFAULTS fallback has already been applied. A stored value outside
    [MIN_PHASES, MAX_PHASES] is CLAMPED rather than raising: a bad config value
    must not take dispatch down, and a clamped program is still coherent.
    """
    key = _CONFIG_KEY[track]
    raw = None
    if config is not None:
        raw = config.get(key) if isinstance(config, dict) else getattr(config, key, None)
    if raw is None:
        raw = 4 if track == TRACK_WALKER else 5
    total = max(MIN_PHASES, min(MAX_PHASES, int(raw)))
    return PhasePlan(track=track, total=total)


def compress_phase_map(authored_phases: list[int], slots: int) -> dict[int, int]:
    """Map each AUTHORED curriculum phase onto a teaching slot (D4).

    Returns {authored_phase: slot}. Never drops an authored phase — a dropped
    DVIC item is a safety gap, not a shorter course.

    Authored phase numbers are treated as an ORDERED SET, not as slot numbers:
    the mapping is positional, so a curriculum authored as [2,4,7] compresses the
    same as [1,2,3]. This matters for the walker track, where ADR-281 seeds a
    phase 0 (the ORE day) — it is simply the first authored phase. The driver
    curriculum starts at 1 (verified on staging: 83 items, phases 1-3), and
    phase 0 is walker-only by design.

    Two directions:

    **Compression** (authored > slots): merge adjacent authored phases into the
    same slot, in curriculum order.

        authored=[1,2,3,4], slots=2  ->  {1:1, 2:1, 3:2, 4:2}

    **Expansion** (authored < slots): map 1:1 onto the first slots and leave the
    trailing slots empty (D4 addendum, 2026-08-22). A trailing empty slot is a
    practice/consolidation day before observation, not an error — the phase gate
    passes a phase with no mandatory tasks, so it cannot stall a trainee.

        authored=[1,2,3], slots=4    ->  {1:1, 2:2, 3:3}   (slot 4 empty)
    """
    ordered = sorted(set(authored_phases))
    if not ordered or slots <= 0:
        return {}
    if len(ordered) <= slots:
        return {p: i + 1 for i, p in enumerate(ordered)}
    # Compression: distribute authored phases across slots as evenly as
    # possible, keeping curriculum order. Earlier slots absorb the remainder so
    # the merged (heavier) phases land early, leaving the run-up to observation
    # lighter rather than heavier.
    out: dict[int, int] = {}
    n, base, extra = len(ordered), len(ordered) // slots, len(ordered) % slots
    i = 0
    for slot in range(1, slots + 1):
        take = base + (1 if slot <= extra else 0)
        for p in ordered[i : i + take]:
            out[p] = slot
        i += take
    assert i == n, "every authored phase must land in a slot"
    return out
