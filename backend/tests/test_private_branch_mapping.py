"""The public→private branch mapping is written in three places.

`master -> main`, everything else -> same name. It appears in:

  1. .github/workflows/ci.yml        (the pull step, at build time)
  2. scripts/setup_private_repo.sh   (developer setup)
  3. scripts/check_private_branch_ready.sh (the pre-merge guard)

Three copies of one rule is the risk this file exists for. If they disagree,
the guard checks a different branch than CI pulls — and passes while the merge
it was meant to block goes through.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_GUARD = _ROOT / "scripts" / "check_private_branch_ready.sh"
_SETUP = _ROOT / "scripts" / "setup_private_repo.sh"


def test_ci_maps_master_to_main():
    text = _CI.read_text()
    assert re.search(r'"\$PUB_BRANCH"\s*=\s*"master"\s*\]\s*;\s*then\s+PRIV_BRANCH=main', text), (
        "ci.yml no longer maps master -> main; the guard would check the wrong branch"
    )


def test_the_guard_uses_the_same_mapping():
    text = _GUARD.read_text()
    assert re.search(r'map_branch\(\)\s*\{\s*\[\s*"\$1"\s*=\s*"master"\s*\]\s*&&\s*echo\s+"main"', text)


def test_setup_script_agrees_if_it_maps_at_all():
    if not _SETUP.exists():
        return
    text = _SETUP.read_text()
    if "master" not in text:
        return
    assert "main" in text, "setup_private_repo.sh mentions master but not main"


class TestTheGuardIsWiredIn:
    def test_it_runs_on_pull_requests_only(self):
        """On a push the merge has already happened — there is nothing left to
        block, and the job would fail every post-merge run until someone
        synced."""
        text = _CI.read_text()
        i = text.index("private-branch-ready:")
        block = text[i : i + 700]
        assert "if: github.event_name == 'pull_request'" in block

    def test_it_compares_base_against_head(self):
        text = _CI.read_text()
        i = text.index("check_private_branch_ready.sh")
        block = text[i : i + 200]
        assert "github.base_ref" in block and "github.head_ref" in block

    def test_the_guard_script_is_executable(self):
        import os, stat

        assert _GUARD.exists()
        assert os.stat(_GUARD).st_mode & stat.S_IXUSR, "CI invokes it via bash, but keep it runnable"


class TestTheGuardScopesToCode:
    def test_docs_only_drift_does_not_fail_a_pr(self):
        """The private repo carries ADRs and journals, synced on every push, so
        the branches diverge by documentation within minutes of any commit.
        Failing a PR over a journal file is friction that gets a check
        disabled — and a disabled check catches nothing."""
        text = _GUARD.read_text()
        assert "CODE_DRIFT=" in text
        assert 'if [ "$BEHIND" -eq 0 ] || [ "$CODE_DRIFT" -eq 0 ]' in text

    def test_it_scopes_to_what_ci_actually_pulls(self):
        text = _GUARD.read_text()
        i = text.index("CODE_DRIFT=")
        window = text[i : i + 400]
        for path in ("backend/app", "backend/tests", "asheflow_private"):
            assert path in window, f"code-drift scope omits {path}"

    def test_a_missing_private_branch_skips_rather_than_fails(self):
        """A feature branch with no private counterpart falls back to staging at
        pull time. That is documented behaviour, not drift."""
        text = _GUARD.read_text()
        # Measure from the ECHO, not the first mention — the comment above it
        # says the same words, and a window from there stops short of the exit.
        i = text.index('echo "Private branch')
        assert "exit 0" in text[i : i + 200], "a missing private branch must skip, not fail"
