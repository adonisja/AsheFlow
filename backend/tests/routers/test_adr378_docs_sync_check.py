"""A design-only session must not leave documentation on one machine (ADR-378).

docs/decisions/, docs/journals/, docs/LEARNING_GUIDE.md and CLAUDE.md are
gitignored from the public repo and reach AsheFlow-private only through the
pre-push hook. That hook fires on `git push`. A session producing ONLY
documentation has nothing to commit, so the push is a no-op, the hook never
runs, and the document exists on exactly one laptop.

ADR-377 sat unsynced for that reason -- written, correct, complete, invisible.
Three documentation audits in one week found the artifacts present every time
and the SYNC missing once. The failure is not "we forget to write docs", it is
"writing docs does not push".

No git hook can catch this: there is no event to hang off when nothing is
committed. These tests pin the tooling that replaces the habit.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECK = ROOT / "scripts" / "check_docs_synced.sh"
SYNC = ROOT / "scripts" / "setup_private_repo.sh"
INSTALL = ROOT / "scripts" / "install_hooks.sh"


def _sh(*args, **kw):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)


class TestTheCheckerExists:
    def test_it_is_executable(self):
        assert CHECK.exists(), "check_docs_synced.sh is gone"
        assert os.stat(CHECK).st_mode & stat.S_IXUSR, "not executable"

    def test_it_is_valid_bash(self):
        assert _sh("bash", "-n", CHECK).returncode == 0

    def test_it_watches_every_gitignored_doc_path(self):
        """Miss one and that path silently never triggers a warning.

        Parses the WATCHED array rather than grepping the file: every one of
        these paths is also named in the comments, so a whole-file grep passes
        even after a path is deleted from the array. Measured -- that version
        survived the mutation that removed docs/journals.
        """
        src = CHECK.read_text()
        block = src.split("WATCHED=(", 1)[1].split(")", 1)[0]
        for path in ("docs/decisions", "docs/journals",
                     "docs/LEARNING_GUIDE.md", "CLAUDE.md"):
            assert path in block, (
                f"{path} is gitignored but missing from the WATCHED array — "
                f"changes there would never warn"
            )

    def test_it_names_the_stale_file(self):
        """'docs are stale' sends people hunting; name the file."""
        assert "newest_file" in CHECK.read_text()


class TestTheSyncWritesAMarker:
    """Without the marker the checker has nothing to compare against -- the
    clone lives in a mktemp dir that is deleted, so nothing local knows when
    the last sync happened."""

    def test_the_sync_writes_the_marker(self):
        assert "last_private_sync" in SYNC.read_text()

    def test_the_marker_lives_under_dot_git(self):
        """Machine-local state. Committing it to either repo would make one
        machine's sync time look like everyone's."""
        src = SYNC.read_text()
        assert '.git/last_private_sync' in src, (
            "the marker must be under .git/, not in the working tree"
        )

    def test_the_checker_reads_the_same_path(self):
        assert ".git/last_private_sync" in CHECK.read_text()


class TestDocsOnlyMode:
    def test_the_flag_is_parsed(self):
        assert '"--docs-only"' in SYNC.read_text()

    def test_it_guards_the_proprietary_block(self):
        """--docs-only must skip the code copy; otherwise it is just a slower
        full sync with a misleading name."""
        src = SYNC.read_text()
        assert "if $DOCS_ONLY; then" in src
        assert "skipping proprietary code" in src

    def test_the_full_sync_is_still_the_default(self):
        """A bare invocation must still mirror proprietary code -- the pre-push
        hook calls it with no arguments."""
        src = SYNC.read_text()
        assert "DOCS_ONLY=false" in src, "docs-only must not be the default"

    def test_docs_only_commits_are_labelled(self):
        """A reader of the private history must be able to tell which commits
        refreshed proprietary code and which did not."""
        assert "(docs only)" in SYNC.read_text()

    def test_the_script_is_valid_bash(self):
        assert _sh("bash", "-n", SYNC).returncode == 0


class TestTheRuleIsWrittenDown:
    def test_claude_md_documents_the_design_only_case(self):
        """Tooling nobody knows about is not enforcement.

        CLAUDE.md is gitignored, so it is absent from the PUBLIC checkout CI
        runs against -- this test broke the build on its first push. Skipping on
        absence is correct here and is NOT the banned ImportError skip guard
        (ADR-311): that rule exists because proprietary modules ARE supplied by
        CI, so a missing one is a real breakage. CLAUDE.md is deliberately never
        copied there. Locally, where it exists, the assertion is exact.
        """
        claude = ROOT / "CLAUDE.md"
        if not claude.exists():
            pytest.skip("CLAUDE.md is gitignored and absent from the public checkout")
        src = claude.read_text()
        assert "check_docs_synced.sh" in src
        assert "--docs-only" in src

    def test_the_installer_explains_what_hooks_cannot_catch(self):
        src = INSTALL.read_text()
        assert "design-only" in src.lower()
        assert _sh("bash", "-n", INSTALL).returncode == 0
