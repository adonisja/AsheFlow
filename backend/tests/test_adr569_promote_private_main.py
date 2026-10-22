"""Promoting private staging to private main is one safe command (ADR-569).

The script is run for real against a throwaway local git repo standing in for
AsheFlow-private (PRIVATE_REPO), so these tests exercise the git operations,
not a description of them.
"""
import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "promote_private_main.sh"
_GUARD = _ROOT / "scripts" / "check_private_branch_ready.sh"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def private(tmp_path):
    """A bare 'private repo' with main one commit behind staging."""
    work, bare = tmp_path / "work", tmp_path / "private.git"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com"); _git(work, "config", "user.name", "t")
    (work / "backend/app/routers").mkdir(parents=True)
    (work / "backend/app/routers/rts.py").write_text("old\n")
    _git(work, "add", "."); _git(work, "commit", "-q", "-m", "base")
    _git(work, "checkout", "-q", "-b", "staging")
    (work / "backend/app/routers/rts.py").write_text("new\n")
    _git(work, "commit", "-q", "-am", "ADR-567 legal_name writers")
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return work, bare


def _run(bare, *args, input_text=None):
    env = {**os.environ, "PRIVATE_REPO": str(bare)}
    return subprocess.run(["bash", str(_SCRIPT), *args], env=env, capture_output=True, text=True, input=input_text)


def _ref(bare, name):
    return _git(bare, "rev-parse", f"refs/heads/{name}")


def test_it_fast_forwards_main_and_names_the_code_files(private):
    _work, bare = private
    out = _run(bare, "--yes")
    assert out.returncode == 0, out.stderr
    assert _ref(bare, "main") == _ref(bare, "staging")
    assert "backend/app/routers/rts.py" in out.stdout


def test_up_to_date_is_a_no_op(private):
    _work, bare = private
    _run(bare, "--yes")
    out = _run(bare, "--yes")
    assert out.returncode == 0 and "Nothing to promote" in out.stdout


def test_it_never_forces_over_commits_only_main_has(private):
    """Someone's work on main must not be discarded by a promotion."""
    work, bare = private
    _git(work, "checkout", "-q", "main")
    (work / "hotfix.txt").write_text("prod-only fix\n")
    _git(work, "add", "."); _git(work, "commit", "-q", "-m", "prod hotfix")
    _git(work, "push", "-q", str(bare), "main")
    before = _ref(bare, "main")
    out = _run(bare, "--yes")
    assert out.returncode == 2 and "not a" in out.stderr and "prod hotfix" in out.stderr
    assert _ref(bare, "main") == before, "main must be untouched"


def test_without_yes_it_asks_and_a_no_changes_nothing(private):
    _work, bare = private
    before = _ref(bare, "main")
    out = _run(bare, input_text="n\n")
    assert out.returncode == 1 and _ref(bare, "main") == before


def test_the_guard_points_to_it():
    text = _GUARD.read_text()
    assert "scripts/promote_private_main.sh" in text
    assert text.index("promote_private_main.sh") < text.index("--force-with-lease"), \
        "the fast-forward comes first; the manual force is the fallback"


def test_it_never_uses_force():
    src = _SCRIPT.read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "--force" not in code and " -f " not in code and "+refs" not in code
