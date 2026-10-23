"""ADR-575: every Python requirements file in the repo is CVE-audited in CI.

Walks the repository for requirements files rather than listing the expected
ones (a list goes stale the day someone adds an image), then requires a
`pip-audit -r requirements.txt` step whose working-directory is that file's
directory. The bot sat on aiohttp 3.9.3 with 80 advisories because only
backend/ was audited.
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()


def _requirements_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines()
            if re.search(r"(^|/)requirements[^/]*\.txt$", p) and "node_modules" not in p]


def _audited() -> set[str]:
    found = set()
    for m in re.finditer(r"working-directory:\s*(\S+)\s*\n\s*run:\s*pip-audit -r (\S+)", CI):
        found.add(f"{m.group(1)}/{m.group(2)}")
    for m in re.finditer(r"pip-audit -r (\S+/\S+)", CI):
        found.add(m.group(1))
    return found


def test_the_walk_finds_the_known_files():
    files = _requirements_files()
    assert "backend/requirements.txt" in files and "bot/requirements.txt" in files


def test_every_requirements_file_is_audited():
    missing = sorted(set(_requirements_files()) - _audited())
    assert not missing, (
        f"{missing} is never CVE-audited: add a 'pip-audit -r' step for it to the "
        "Dependency CVE audit job in .github/workflows/ci.yml (ADR-575)")
