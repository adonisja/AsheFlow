"""ADR-501 — the pre-push coverage check requires a complete deep dive.

The check is pointed at a temporary docs tree. The real docs/ is gitignored and
absent from CI's public checkout, and a test that reads it would pass or fail
depending on the machine (the ADR-494 lesson).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_adr_coverage.py"
ALL_PARTS = "".join(f"\n## Part {n} — x\n\nbody\n" for n in range(1, 10))


@pytest.fixture
def cov(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_adr_coverage", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "docs" / "deep-dives").mkdir(parents=True)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DEEP_DIVES", tmp_path / "docs" / "deep-dives")
    return mod


def _write(cov, name, body):
    (cov.DEEP_DIVES / name).write_text(body)


class TestIdentityNotMention:
    def test_a_matching_filename_with_all_parts_passes(self, cov):
        _write(cov, "ADR-600-Thing.md", "---\nfeature: ADR-600\n---\n" + ALL_PARTS)
        assert cov.deep_dive_gap("600") is None

    def test_the_feature_line_covers_several_adrs(self, cov):
        _write(cov, "Combined.md", "---\nfeature: ADR-600, ADR-601\n---\n" + ALL_PARTS)
        assert cov.deep_dive_gap("600") is None and cov.deep_dive_gap("601") is None

    def test_a_mention_in_the_body_does_not_count(self, cov):
        _write(cov, "ADR-700-Other.md",
               "---\nfeature: ADR-700\nrelated: ADR-600\n---\nSee ADR-600.\n" + ALL_PARTS)
        assert cov.deep_dive_gap("600") is not None, (
            "a deep dive that cites ADR-600 in passing must not satisfy ADR-600 forever"
        )

    def test_a_number_prefix_is_not_a_match(self, cov):
        _write(cov, "X.md", "---\nfeature: ADR-6000\n---\n" + ALL_PARTS)
        assert cov.deep_dive_gap("600") is not None, "ADR-600 must not match ADR-6000"

    def test_no_deep_dive_is_reported(self, cov):
        gap = cov.deep_dive_gap("600")
        assert gap and "ADR-600" in gap


class TestStructure:
    def test_a_stub_fails_and_names_the_missing_parts(self, cov):
        _write(cov, "ADR-600-Stub.md", "---\nfeature: ADR-600\n---\n## Part 1 — x\n## Part 5 — y\n")
        gap = cov.deep_dive_gap("600")
        assert gap and "'## Part 2'" in gap and "'## Part 9'" in gap
        assert "'## Part 1'" not in gap and "'## Part 5'" not in gap

    def test_one_complete_candidate_is_enough(self, cov):
        _write(cov, "ADR-600-Old-Stub.md", "---\nfeature: ADR-600\n---\n## Part 1 — x\n")
        _write(cov, "ADR-600-Full.md", "---\nfeature: ADR-600\n---\n" + ALL_PARTS)
        assert cov.deep_dive_gap("600") is None

    def test_a_heading_must_start_its_line(self, cov):
        body = "---\nfeature: ADR-600\n---\n" + "".join(f"text ## Part {n}\n" for n in range(1, 10))
        _write(cov, "ADR-600-Inline.md", body)
        assert cov.deep_dive_gap("600") is not None, "a heading must start its line"


class TestItIsWiredIntoTheGate:
    def test_missing_artifacts_reports_the_deep_dive(self, cov, monkeypatch):
        monkeypatch.setattr(cov, "deep_dive_gap", lambda n: "a deep dive (test)")
        monkeypatch.setattr(cov, "DECISIONS", cov.ROOT / "nope")
        monkeypatch.setattr(cov, "JOURNALS", cov.ROOT / "nope")
        monkeypatch.setattr(cov, "GUIDE", cov.ROOT / "nope.md")
        assert "a deep dive (test)" in cov.missing_artifacts("600")
