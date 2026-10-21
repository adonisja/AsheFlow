"""CI reuses a passing backend-test run for byte-identical code (ADR-552).

The owner, waiting on PR #82: the same ~6,500 tests ran three times per
release on unchanged code (staging push, PR, master push), ~20 min each.
These pin the reuse rule and, above all, D4: any doubt runs the tests.
"""
import importlib.util
import json
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_reuse_tests", ROOT / "scripts" / "ci_reuse_tests.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
FP = R.fingerprint("pubtree", "privtree", "Python 3.12.7")


def _art(fp=FP, run=111, age=timedelta(hours=1), expired=False):
    return {"name": R.MARKER_PREFIX + fp, "expired": expired,
            "workflow_run": {"id": run}, "created_at": (NOW - age).isoformat().replace("+00:00", "Z")}


# ── D1: the fingerprint ────────────────────────────────────────────────────

def test_any_input_changing_changes_the_fingerprint():
    base = ("pub", "priv", "Python 3.12.7")
    fps = {R.fingerprint(*base), R.fingerprint("pub2", "priv", "Python 3.12.7"),
           R.fingerprint("pub", "priv2", "Python 3.12.7"), R.fingerprint("pub", "priv", "Python 3.12.8")}
    assert len(fps) == 4


@pytest.mark.parametrize("args", [("", "p", "v"), ("p", "", "v"), ("p", "p", " ")])
def test_a_missing_input_means_no_fingerprint(args):
    with pytest.raises(ValueError):
        R.fingerprint(*args)


# ── D2: what can be reused ─────────────────────────────────────────────────

def test_a_recent_marker_from_another_run_is_reused():
    hit = R.find_reusable({"artifacts": [_art()]}, FP, now=NOW, current_run_id=999)
    assert hit["run_id"] == 111


@pytest.mark.parametrize("art,why", [
    (_art(fp="0" * 64), "a different fingerprint"),
    (_art(expired=True), "an expired artifact"),
    (_art(run=999), "this run itself"),
    (_art(age=timedelta(hours=25)), "older than 24 h"),
])
def test_unusable_markers_are_ignored(art, why):
    assert R.find_reusable({"artifacts": [art]}, FP, now=NOW, current_run_id=999) is None, why


def test_the_newest_usable_marker_wins():
    arts = [_art(run=1, age=timedelta(hours=5)), _art(run=2, age=timedelta(hours=2))]
    assert R.find_reusable({"artifacts": arts}, FP, now=NOW, current_run_id=9)["run_id"] == 2


# ── D4: doubt means run the tests ──────────────────────────────────────────

def _lookup_output(tmp_path, monkeypatch, run):
    out = tmp_path / "out"; summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out)); monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r"); monkeypatch.setenv("GITHUB_RUN_ID", "999")
    with patch.object(R.subprocess, "run", side_effect=run):
        R.lookup(FP)
    return out.read_text(), summary.read_text()


@pytest.mark.parametrize("failure", [
    subprocess.CalledProcessError(1, "gh"), subprocess.TimeoutExpired("gh", 30), FileNotFoundError("gh"),
])
def test_any_lookup_failure_runs_the_tests(tmp_path, monkeypatch, failure):
    out, summary = _lookup_output(tmp_path, monkeypatch, failure)
    assert out.strip() == "hit=false" and "will run" in summary


def test_garbage_from_the_api_runs_the_tests(tmp_path, monkeypatch):
    out, _ = _lookup_output(tmp_path, monkeypatch,
                            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="not json"))
    assert out.strip() == "hit=false"


def test_a_reuse_is_never_silent(tmp_path, monkeypatch):
    body = json.dumps({"artifacts": [{**_art(), "created_at": datetime.now(timezone.utc).isoformat()}]})
    out, summary = _lookup_output(tmp_path, monkeypatch,
                                  lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=body))
    assert "hit=true" in out and "run_id=111" in out
    assert "Reused backend tests" in summary and "/actions/runs/111" in summary


def test_an_unfingerprinted_run_runs_the_tests(tmp_path, monkeypatch):
    out = tmp_path / "out"; monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("PRIVATE_TREE", raising=False)
    R.main(["x", "lookup", "none (missing private tree)"])
    assert out.read_text().strip() == "hit=false"


# ── The workflow wires it the way the ADR says ─────────────────────────────

# Parsed from TEXT, not YAML: PyYAML isn't in requirements.txt (it was only
# installed on the dev machine), so `import yaml` would have broken collection
# in the very CI this pins. actionlint validated the YAML itself (ADR-552).
CI_TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
JOB = CI_TEXT[CI_TEXT.index("\n  test:\n"):CI_TEXT.index("\n  # ── 3. FRESH-DATABASE MIGRATIONS")]
_BLOCKS = re.split(r"\n      - ", JOB)[1:]
STEPS = {}
for b in _BLOCKS:
    m = re.match(r"(?:uses: [^\n]+\n\s+)?name: (.+)", b) or re.match(r"name: (.+)", b)
    if m:
        STEPS[m.group(1).strip()] = b
NAMES = list(STEPS)


def _step(name):
    return STEPS[name]


def test_only_run_tests_is_skipped_on_a_hit():
    gated = [n for n, b in STEPS.items() if "steps.reuse.outputs.hit != 'true'" in b]
    assert gated == ["Run tests", "Record that this exact code passed (ADR-552)", "Upload the pass marker (ADR-552)"]


def test_the_floor_and_drift_check_still_run_before_the_decision():
    i = NAMES.index("Look for an identical passing run (ADR-552)")
    assert NAMES.index("Assert the suite did not silently shrink") < i
    assert NAMES.index("Proprietary code must match the public models") < i
    for n in ("Assert the suite did not silently shrink", "Proprietary code must match the public models"):
        assert "\n        if:" not in _step(n), f"{n} must never be skipped"


def test_a_crash_in_the_lookup_cannot_fail_or_skip():
    assert "continue-on-error: true" in _step("Look for an identical passing run (ADR-552)")


def test_the_private_tree_is_captured_before_the_clone_is_deleted():
    run = _step("Pull proprietary source + tests from AsheFlow-private")
    assert run.index("PRIVATE_TREE=") < run.index("rm -rf /tmp/asheflow-private")


def test_the_job_can_read_artifacts():
    head = JOB[:JOB.index("steps:")]
    assert "permissions:\n      contents: read\n      actions: read" in head


def test_the_marker_name_matches_the_script():
    upload = _step("Upload the pass marker (ADR-552)")
    assert f"name: {R.MARKER_PREFIX}" + "${{ steps.reuse.outputs.fingerprint }}" in upload
    assert "retention-days: 2" in upload


def test_the_parser_found_the_job():
    """Guard the guard: a parsing slip would make every check above vacuous."""
    assert len(NAMES) >= 8 and "Run tests" in NAMES and "Install dependencies" in NAMES
