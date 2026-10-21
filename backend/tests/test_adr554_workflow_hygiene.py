"""Workflow scripts never interpolate untrusted input; actionlint gates CI (ADR-554).

actionlint, run by hand for ADR-552, found ${{ github.head_ref }} inside a run:
script in the job that had just written the private deploy key to disk. ${{ }}
is substituted into the script TEXT before bash parses it, so a crafted branch
name becomes code. These read the workflow as text (PyYAML is not a dependency,
ADR-552 Case 1).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

# Contexts an outside party can choose (GitHub's security guidance, "untrusted input").
UNTRUSTED = re.compile(
    r"\$\{\{\s*github\.(head_ref|base_ref|event\.(pull_request|issue|comment|review|"
    r"head_commit|commits|pages|discussion)[^}]*)\s*\}\}")


def _run_blocks(text: str):
    """(line number, script) for every `run:` block -- inline or `|` block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2)
        start = i + 1
        if rest.strip() in ("|", ">", "|-", ">-"):
            body, i = [], i + 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append(lines[i]); i += 1
            yield start, "\n".join(body)
        else:
            yield start, rest
            i += 1


def test_the_scan_sees_the_scripts():
    """Guard the guard: a parsing slip would make the next test vacuous."""
    blocks = [b for p in WORKFLOWS for b in _run_blocks(p.read_text())]
    assert len(blocks) >= 15
    assert any("check_private_branch_ready.sh" in s for _, s in blocks)


def test_the_detector_catches_its_planted_samples():
    for bad in ('bash x.sh "${{ github.head_ref }}"', "echo ${{ github.event.pull_request.title }}",
                "echo ${{github.base_ref}}"):
        assert UNTRUSTED.search(bad), bad
    assert not UNTRUSTED.search('bash x.sh "$HEAD_REF"')
    assert not UNTRUSTED.search("echo ${{ github.sha }}")


def test_no_script_interpolates_untrusted_input():
    offenders = [f"{p.name}:{line}" for p in WORKFLOWS
                 for line, script in _run_blocks(p.read_text()) if UNTRUSTED.search(script)]
    assert not offenders, (
        "Untrusted input inside a run: script (ADR-554). Pass it through env: and "
        "use \"$VAR\" in the script:\n  " + "\n  ".join(offenders))


CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()


def test_the_readiness_job_passes_refs_through_env():
    assert "HEAD_REF: ${{ github.head_ref }}" in CI and "BASE_REF: ${{ github.base_ref }}" in CI
    assert 'check_private_branch_ready.sh "$BASE_REF" "$HEAD_REF"' in CI


def test_the_lint_job_is_pinned_and_verified():
    job = CI[CI.index("  workflow-lint:"):]
    job = job[:job.index("\n  # ──", 10)]
    assert re.search(r'ACTIONLINT_VERSION: "\d+\.\d+\.\d+"', job), "pin an exact version, never latest"
    assert re.search(r'ACTIONLINT_SHA256: "[0-9a-f]{64}"', job)
    assert "sha256sum -c -" in job, "the download must be verified before it runs"


def test_both_deploys_need_the_lint():
    needs = re.findall(r"needs: \[([^\]]*)\]", CI)
    deploy_needs = [n for n in needs if "migrations" in n and "test" in n]
    assert len(deploy_needs) == 2 and all("workflow-lint" in n for n in deploy_needs)
