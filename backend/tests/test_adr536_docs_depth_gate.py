"""ADR-536 — the docs gate checks depth, not just headings.

ADR-528..534's deep dives and lessons passed the ADR-501 structural check
while being summaries (547-1,504-word deep dives vs a 12,232-word calibration;
366-725-word lessons vs 1,637). These pin the floors that would have caught
them. Run against a temporary docs tree: the real docs/ is gitignored and absent
from CI's public checkout (the ADR-494 lesson).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_adr_coverage.py"
N = "600"  # >= DEPTH_FROM


def _filler(n):  # real-looking prose to reach a word floor without changing structure
    return " ".join(["the check ran against the real handler and recorded its output"] * (n // 10 + 1))


GOOD_CASE = '''### Case 1 — The thing broke (`abc1234`)
**Symptom.** The page said Driver.
**Why it stayed invisible.** The value looked plausible.
**Diagnosis.**
```
RESULT: manager changed driver -> admin
```
**Wrong / right.**
```python
# WRONG — checks the target
# RIGHT — checks the grant
```
**Fix and proof.** Probe: 3 failed.
**Lesson.** *Authorise the grant.*
'''

def good_deep_dive(extra_case=""):
    parts = {
        1: "Mental model. " + _filler(400),
        2: "Decisions. " + _filler(300),
        3: "Code. " + _filler(300),
        4: "None: web deploy only.",
        5: "| # | where | one line | found by |\n|---|---|---|---|\n| 1 | x | y | z |\n\n" + GOOD_CASE + extra_case,
        6: "| rung | proves |\n|---|---|\n**As climbed:** 1 → 2 → 3.",
        7: "Gaps. " + _filler(100),
        8: "Principles. " + _filler(100),
        9: "Reference. [[ADR-600-Thing|ADR-600]]",
    }
    return f"---\nfeature: ADR-{N}\n---\n" + "".join(f"\n## Part {k} — x\n\n{v}\n" for k, v in parts.items())


GOOD_LESSON = f'''## Lesson — Authorise the grant, not just the target (ADR-{N})

### 1. Recognition cue
A guard reads the target's current role. {_filler(250)}

### 2. The trap
```python
# WRONG — checks who you edit
# RIGHT — checks what you grant
```

### 3. The principle
*Authorise the value granted, not only the object changed.*
{_filler(150)}

### 4. How it was verified
Probe: edit check removed, 3 failed.

### 5. Failure modes
Tightening edit silently.
'''


@pytest.fixture
def cov(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_adr_coverage_536", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for d in ("deep-dives", "decisions", "journals"):
        (tmp_path / "docs" / d).mkdir(parents=True)
    (tmp_path / "docs" / "decisions" / f"ADR-{N}-Thing.md").write_text("x")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DEEP_DIVES", tmp_path / "docs" / "deep-dives")
    monkeypatch.setattr(mod, "DECISIONS", tmp_path / "docs" / "decisions")
    monkeypatch.setattr(mod, "GUIDE", tmp_path / "docs" / "LEARNING_GUIDE.md")
    return mod


def _put(cov, dive=None, lesson=None):
    if dive is not None:
        (cov.DEEP_DIVES / f"ADR-{N}-Thing.md").write_text(dive)
    if lesson is not None:
        cov.GUIDE.write_text("# Guide\n\n---\n\n" + lesson + "\n---\n")


def _gaps(cov):
    return " | ".join(cov.depth_gaps(N))


def test_a_complete_deep_dive_and_lesson_pass(cov):
    _put(cov, good_deep_dive(), GOOD_LESSON)
    assert cov.depth_gaps(N) == []


def test_old_adrs_are_not_gated(cov):
    """D4: the existing corpus predates the standard."""
    assert cov.depth_gaps("534") == []


# ── deep dive floors: each check bites on its own ──────────────────────────

def test_a_summary_length_deep_dive_fails(cov):
    thin = "---\nfeature: ADR-600\n---\n" + "".join(f"\n## Part {k} — x\n\nshort.\n" for k in range(1, 10))
    _put(cov, thin, GOOD_LESSON)
    assert "words (floor 1200" in _gaps(cov)


def test_a_casebook_without_a_summary_table_fails(cov):
    _put(cov, good_deep_dive().replace("| # | where | one line | found by |\n|---|---|---|---|\n| 1 | x | y | z |\n", ""), GOOD_LESSON)
    assert "summary table" in _gaps(cov)


def test_a_case_missing_its_frame_fails_and_is_named(cov):
    bare = "### Case 2 — A bare note\nSomething happened and we fixed it.\n"
    _put(cov, good_deep_dive(extra_case=bare), GOOD_LESSON)
    g = _gaps(cov)
    assert "Case 2 — A bare note" in g and "why it stayed invisible" in g


def test_a_casebook_with_no_wrong_right_fails(cov):
    _put(cov, good_deep_dive().replace("WRONG", "bad").replace("RIGHT", "good"), GOOD_LESSON)
    assert "WRONG/RIGHT" in _gaps(cov)


def test_a_casebook_with_no_real_output_fails(cov):
    _put(cov, good_deep_dive().replace("```python", "").replace("```", ""), GOOD_LESSON)
    assert "fenced block" in _gaps(cov)


def test_a_ladder_without_as_climbed_fails(cov):
    _put(cov, good_deep_dive().replace("**As climbed:** 1 → 2 → 3.", ""), GOOD_LESSON)
    assert "as climbed" in _gaps(cov)


def test_a_broken_wikilink_fails(cov):
    """Today: [[ADR-256|ADR-256]] and a redirect-stub citation slipped through."""
    _put(cov, good_deep_dive().replace("[[ADR-600-Thing|ADR-600]]", "[[ADR-256|ADR-256]]"), GOOD_LESSON)
    assert "broken wikilinks: ADR-256" in _gaps(cov)


# ── lesson floors ──────────────────────────────────────────────────────────

def test_a_rule_only_lesson_fails(cov):
    _put(cov, good_deep_dive(), f"## Lesson — Do the thing (ADR-{N})\n\nAlways do the thing.\n")
    g = _gaps(cov)
    for need in ("words (floor 500", "recognition-cue", "WRONG/RIGHT", "italic principle",
                 "verification evidence", "failure-modes"):
        assert need in g, need


@pytest.mark.parametrize("remove,expect", [
    ("### 1. Recognition cue", "recognition-cue"),
    ("*Authorise the value granted, not only the object changed.*", "italic principle"),
    ("Probe: edit check removed, 3 failed.", "verification evidence"),
    ("### 5. Failure modes", "failure-modes"),
])
def test_each_lesson_element_is_checked(cov, remove, expect):
    _put(cov, good_deep_dive(), GOOD_LESSON.replace(remove, ""))
    assert expect in _gaps(cov)


def test_it_is_wired_into_missing_artifacts(cov):
    _put(cov, "---\nfeature: ADR-600\n---\n" + "".join(f"\n## Part {k} — x\n\nshort.\n" for k in range(1, 10)), GOOD_LESSON)
    assert any("too thin" in m for m in cov.missing_artifacts(N))
